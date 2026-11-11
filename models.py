from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(15), unique=True, nullable=False)

class Partner(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(15), unique=True, nullable=False)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item = db.Column(db.String(100), nullable=False)
    total = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), default="placed")
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    partner_id = db.Column(db.Integer, db.ForeignKey("partner.id"))
    room_code = db.Column(db.String(10))
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Integer, nullable=False)
class PushSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    endpoint = db.Column(db.Text, nullable=False)
    p256dh = db.Column(db.String(200), nullable=False)
    auth = db.Column(db.String(100), nullable=False)