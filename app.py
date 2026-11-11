import os
import json
import requests
from pywebpush import webpush, WebPushException
from flask import Flask, render_template, redirect, request, session, url_for, flash, jsonify

from models import db, Customer, Partner, Order, Product, PushSubscription

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-later")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///zepto.db"
db.init_app(app)

NETCALL_URL = os.environ.get("NETCALL_URL", "http://127.0.0.1:5000")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "BNZQaizqQkg4cmLVUTXx4vobDorYtRyo5Iz0YEY7iS_WwaWnk-yHXy03-MoLlDhjXIcqFdnnVZ2wUyU-5hF4HUs")
VAPID_PRIVATE_KEY_FILE = os.environ.get("VAPID_PRIVATE_KEY_FILE", os.path.join(app.root_path, "private_key.pem"))
VAPID_CONTACT = "mailto:admin@example.com"

with app.app_context():
    db.create_all()
    if Product.query.count() == 0:
        for name, price in [("Milk", 30), ("Bread", 40), ("Eggs (6)", 54), ("Bananas", 45), ("Rice 1kg", 70), ("Chips", 20)]:
            db.session.add(Product(name=name, price=price))
        db.session.commit()


# ---------- helpers ----------

def get_room_code(order):
    if not order.room_code:
        reply = requests.post(NETCALL_URL + "/api/create-room")
        order.room_code = reply.json()["code"]
        db.session.commit()
    return order.room_code


def send_call_push(order):
    subs = PushSubscription.query.filter_by(customer_id=order.customer_id).all()
    print("Push subscriptions found:", len(subs))
    message = json.dumps({
        "title": "📞 Delivery partner is calling",
        "body": "Tap to answer your Zepto delivery call",
        "url": NETCALL_URL + "/room/" + order.room_code,
    })
    for sub in subs:
        try:
            response = webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=message,
                vapid_private_key=VAPID_PRIVATE_KEY_FILE,
                vapid_claims={"sub": VAPID_CONTACT},
            )
            print("Push sent, status:", response.status_code)
        except WebPushException as e:
            print("Push failed:", e)
            if e.response is not None and e.response.status_code in (404, 410):
                db.session.delete(sub)
                db.session.commit()


@app.context_processor
def cart_count():
    cart = session.get("cart", {})
    return {"cart_count": sum(cart.values())}


# ---------- customer side ----------

@app.route("/")
def home():
    products = Product.query.all()
    return render_template("index.html", products=products)


@app.route("/add-to-cart/<int:product_id>", methods=["POST"])
def add_to_cart(product_id):
    cart = session.get("cart", {})
    key = str(product_id)
    cart[key] = cart.get(key, 0) + 1
    session["cart"] = cart
    return redirect(request.referrer or url_for("home"))


@app.route("/decrease/<int:product_id>", methods=["POST"])
def decrease_item(product_id):
    cart = session.get("cart", {})
    key = str(product_id)
    if cart.get(key, 0) > 1:
        cart[key] -= 1
    session["cart"] = cart
    return redirect(url_for("cart_page"))


@app.route("/remove/<int:product_id>", methods=["POST"])
def remove_item(product_id):
    cart = session.get("cart", {})
    cart.pop(str(product_id), None)
    session["cart"] = cart
    return redirect(url_for("cart_page"))


@app.route("/cart")
def cart_page():
    cart = session.get("cart", {})
    items = []
    total = 0
    for product_id, qty in cart.items():
        product = db.session.get(Product, int(product_id))
        line_total = product.price * qty
        total += line_total
        items.append({"product": product, "qty": qty, "line_total": line_total})
    return render_template("cart.html", items=items, total=total, saved_phone=session.get("phone"), vapid_key=VAPID_PUBLIC_KEY)


@app.route("/place-order", methods=["POST"])
def place_order():
    cart = session.get("cart", {})
    if not cart:
        return redirect(url_for("cart_page"))

    phone = request.form.get("phone", "").strip() or session.get("phone")
    if not phone or not phone.isdigit() or len(phone) != 10:
        return redirect(url_for("cart_page"))

    customer = Customer.query.filter_by(phone=phone).first()
    if customer is None:
        customer = Customer(name="Customer", phone=phone)
        db.session.add(customer)
        db.session.commit()

    parts = []
    total = 0
    for product_id, qty in cart.items():
        product = db.session.get(Product, int(product_id))
        parts.append(f"{product.name} x{qty}")
        total += product.price * qty

    order = Order(item=", ".join(parts), total=total, customer_id=customer.id)
    db.session.add(order)
    db.session.commit()

    session["phone"] = phone
    session["cart"] = {}
    flash("Order confirmed! Thank you! 🎉")
    return redirect(url_for("cart_page"))


@app.route("/customer/<int:order_id>")
def customer_page(order_id):
    order = db.get_or_404(Order, order_id)
    customer = db.session.get(Customer, order.customer_id)
    code = get_room_code(order)
    return render_template("customer.html", order=order, customer=customer, room_url=NETCALL_URL + "/room/" + code, vapid_key=VAPID_PUBLIC_KEY)


# ---------- notifications ----------

@app.route("/sw.js")
def service_worker():
    return app.send_static_file("sw.js")


@app.route("/subscribe", methods=["POST"])
def subscribe_by_phone():
    phone = session.get("phone")
    customer = Customer.query.filter_by(phone=phone).first() if phone else None
    if customer is None:
        return jsonify({"ok": False}), 400
    data = request.get_json()
    sub = PushSubscription.query.filter_by(endpoint=data["endpoint"]).first()
    if sub is None:
        sub = PushSubscription(
            customer_id=customer.id,
            endpoint=data["endpoint"],
            p256dh=data["keys"]["p256dh"],
            auth=data["keys"]["auth"],
        )
        db.session.add(sub)
    else:
        sub.customer_id = customer.id
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/subscribe/<int:order_id>", methods=["POST"])
def subscribe(order_id):
    order = db.get_or_404(Order, order_id)
    data = request.get_json()
    sub = PushSubscription.query.filter_by(endpoint=data["endpoint"]).first()
    if sub is None:
        sub = PushSubscription(
            customer_id=order.customer_id,
            endpoint=data["endpoint"],
            p256dh=data["keys"]["p256dh"],
            auth=data["keys"]["auth"],
        )
        db.session.add(sub)
    else:
        sub.customer_id = order.customer_id
    db.session.commit()
    return jsonify({"ok": True})


# ---------- delivery side ----------

@app.route("/delivery")
def list_orders():
    orders = Order.query.order_by(Order.id.desc()).all()
    rows = []
    for order in orders:
        customer = db.session.get(Customer, order.customer_id)
        rows.append({"order": order, "customer": customer})
    return render_template("orders.html", rows=rows)


@app.route("/delivery/<int:order_id>")
def delivery_page(order_id):
    order = db.get_or_404(Order, order_id)
    customer = db.session.get(Customer, order.customer_id)
    partner = db.session.get(Partner, order.partner_id)
    return render_template("delivery.html", order=order, customer=customer, partner=partner)


@app.route("/call/<int:order_id>")
def start_call(order_id):
    order = db.get_or_404(Order, order_id)
    code = get_room_code(order)
    send_call_push(order)
    return redirect(NETCALL_URL + "/room/" + code)


if __name__ == "__main__":
    app.run(debug=True, port=5001)