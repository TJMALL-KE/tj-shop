import os
import uuid
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta # Added timedelta for subscriptions
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import cloudinary
import cloudinary.uploader

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'tj-super-secret-key')

cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET')
)

database_url = os.environ.get('DATABASE_URL', 'sqlite:///tjmall.db')
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
POCHI_NUMBER = "0724 650 536"
WHATSAPP_NUMBER = "254724650536"

# --- Database Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

class Plan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    price = db.Column(db.Float, nullable=False)
    product_limit = db.Column(db.Integer, nullable=False)

class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False)
    status = db.Column(db.String(20), default='Pending') # Pending, Active, Expired, Rejected
    mpesa_code = db.Column(db.String(20), nullable=True)
    start_date = db.Column(db.DateTime, nullable=True)
    expiry_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='subscriptions')
    plan = db.relationship('Plan')

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    category = db.Column(db.String(50), nullable=True, default='Other')
    seller_name = db.Column(db.String(100), nullable=True)
    seller_phone = db.Column(db.String(20), nullable=True)
    status = db.Column(db.String(20), default='Pending')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    location = db.Column(db.String(200), nullable=False)
    payment_method = db.Column(db.String(50), nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default="Pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    items = db.relationship('OrderItem', backref='order', lazy=True)

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    product = db.relationship('Product', backref='order_items')

with app.app_context():
    db.create_all()
    if not Plan.query.first():
        free_plan = Plan(name='Free', price=0, product_limit=5)
        basic_plan = Plan(name='Basic', price=300, product_limit=50)
        business_plan = Plan(name='Business', price=700, product_limit=200)
        db.session.add_all([free_plan, basic_plan, business_plan])
        db.session.commit()

# --- Context Processor for Navbar Counts ---
@app.context_processor
def inject_counts():
    cart = session.get('cart', {})
    cart_count = sum(cart.values()) if cart else 0
    pending_count = Product.query.filter_by(status='Pending').count()
    orders_count = Order.query.count()
    pending_subs = Subscription.query.filter_by(status='Pending').count() # NEW
    return dict(cart_count=cart_count, pending_count=pending_count, orders_count=orders_count, pending_subs=pending_subs)

# --- Public Routes ---
@app.route('/')
def home():
    search_query = request.args.get('search', '').strip()
    category_filter = request.args.get('category', '').strip()
    sort_by = request.args.get('sort', '').strip()
    
    query = Product.query.filter_by(status='Approved')
    if search_query:
        query = query.filter(Product.name.ilike(f'%{search_query}%'))
    if category_filter:
        query = query.filter(Product.category == category_filter)
    if sort_by == 'price_low':
        query = query.order_by(Product.price.asc())
    elif sort_by == 'price_high':
        query = query.order_by(Product.price.desc())
    elif sort_by == 'newest':
        query = query.order_by(Product.id.desc())
    else:
        query = query.order_by(Product.id.asc())
        
    products = query.all()
    categories = db.session.query(Product.category).filter(Product.status == 'Approved').distinct().all()
    categories = [c[0] for c in categories if c[0]]
    
    return render_template('index.html', products=products, search_query=search_query, 
                           categories=categories, current_category=category_filter, current_sort=sort_by)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        
        if not name or not email or not phone or not password:
            flash('All fields are required.', 'danger')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered. Please login.', 'danger')
            return redirect(url_for('register'))
            
        hashed_password = generate_password_hash(password)
        new_user = User(name=name, email=email, phone=phone, password_hash=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        free_plan = Plan.query.filter_by(name='Free').first()
        if free_plan:
            new_sub = Subscription(user_id=new_user.id, plan_id=free_plan.id, status='Active', start_date=datetime.utcnow())
            db.session.add(new_sub)
            db.session.commit()
        
        flash('Account created successfully! Please login.', 'success')
        return redirect(url_for('seller_login'))
    return render_template('register.html')

@app.route('/seller_login', methods=['GET', 'POST'])
def seller_login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['user_name'] = user.name
            flash(f'Welcome back, {user.name}!', 'success')
            return redirect(url_for('seller_dashboard'))
        else:
            flash('Invalid email or password.', 'danger')
    return render_template('seller_login.html')

@app.route('/seller_logout')
def seller_logout():
    session.pop('user_id', None)
    session.pop('user_name', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('home'))

@app.route('/seller_dashboard')
def seller_dashboard():
    if not session.get('user_id'):
        flash('Please login to view your dashboard.', 'danger')
        return redirect(url_for('seller_login'))
    
    my_products = Product.query.filter_by(user_id=session['user_id']).all()
    my_order_items = OrderItem.query.join(Product).filter(Product.user_id == session['user_id']).order_by(OrderItem.id.desc()).all()
    user_sub = Subscription.query.filter_by(user_id=session['user_id'], status='Active').first()
    
    return render_template('seller_dashboard.html', products=my_products, order_items=my_order_items, user_sub=user_sub)

@app.route('/upgrade')
def upgrade_plan():
    if not session.get('user_id'):
        flash('Please login to view upgrade options.', 'danger')
        return redirect(url_for('seller_login'))
    
    plans = Plan.query.filter(Plan.name != 'Free').all()
    return render_template('upgrade.html', plans=plans)

@app.route('/submit_payment/<int:plan_id>', methods=['POST'])
def submit_payment(plan_id):
    if not session.get('user_id'):
        return redirect(url_for('seller_login'))
    
    mpesa_code = request.form.get('mpesa_code', '').strip().upper()
    
    if not mpesa_code:
        flash('Please enter the M-Pesa code.', 'danger')
        return redirect(url_for('upgrade_plan'))
    
    new_sub = Subscription(user_id=session['user_id'], plan_id=plan_id, status='Pending', mpesa_code=mpesa_code)
    db.session.add(new_sub)
    db.session.commit()
    
    flash('Payment submitted! The admin will verify your code and activate your plan shortly.', 'success')
    return redirect(url_for('seller_dashboard'))

@app.route('/sell', methods=['GET', 'POST'])
def sell_product():
    if request.method == 'POST':
        current_user_id = session.get('user_id')
        if current_user_id:
            sub = Subscription.query.filter_by(user_id=current_user_id, status='Active').first()
            if sub and sub.plan:
                product_count = Product.query.filter_by(user_id=current_user_id).count()
                if product_count >= sub.plan.product_limit:
                    flash(f'You have reached the limit of {sub.plan.product_limit} products for your {sub.plan.name} plan. Please upgrade.', 'danger')
                    return redirect(url_for('seller_dashboard'))

        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip()
        seller_name = request.form.get('seller_name', '').strip()
        seller_phone = request.form.get('seller_phone', '').strip()
        description = request.form.get('description', '').strip()
        price_input = request.form.get('price', '').strip()
        
        if not name or not seller_name or not seller_phone or not category:
            flash('Please fill in all required fields.', 'danger')
            return redirect(url_for('sell_product'))
        
        try:
            price = float(price_input)
            if price <= 0:
                flash('Price must be a positive number.', 'danger')
                return redirect(url_for('sell_product'))
        except (ValueError, TypeError):
            flash('Invalid price. Please enter a valid number (e.g., 4500).', 'danger')
            return redirect(url_for('sell_product'))
        
        image = request.files.get('image')
        image_url = ""
        if image and image.filename != '':
            try:
                upload_result = cloudinary.uploader.upload(image)
                image_url = upload_result.get('secure_url')
            except Exception as e:
                print(f"CLOUDINARY ERROR: {e}")
                flash(f'Image upload failed: {e}', 'danger')
                return redirect(url_for('sell_product'))
        
        new_product = Product(
            name=name, price=price, description=description, category=category,
            image_url=image_url, seller_name=seller_name, 
            seller_phone=seller_phone, status='Pending', user_id=current_user_id
        )
        db.session.add(new_product)
        db.session.commit()
        flash('Your product has been submitted for review.', 'success')
        return redirect(url_for('seller_dashboard') if current_user_id else url_for('home'))
    return render_template('sell.html')

@app.route('/cart')
def view_cart():
    cart = session.get('cart', {})
    cart_items = []
    total = 0
    for product_id, quantity in cart.items():
        product = Product.query.get(int(product_id))
        if product:
            subtotal = product.price * quantity
            total += subtotal
            cart_items.append({'product': product, 'quantity': quantity, 'subtotal': subtotal})
    return render_template('cart.html', cart_items=cart_items, total=total)

@app.route('/add_to_cart/<int:id>')
def add_to_cart(id):
    product = Product.query.get_or_404(id)
    if product.status != 'Approved':
        flash('This product is not available.', 'danger')
        return redirect(url_for('home'))
    cart = session.get('cart', {})
    cart[str(id)] = cart.get(str(id), 0) + 1
    session['cart'] = cart
    flash(f'{product.name} added to cart!', 'success')
    return redirect(url_for('home'))

@app.route('/remove_from_cart/<int:id>')
def remove_from_cart(id):
    cart = session.get('cart', {})
    if str(id) in cart:
        del cart[str(id)]
        session['cart'] = cart
        flash('Item removed from cart.', 'info')
    return redirect(url_for('view_cart'))

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    cart = session.get('cart', {})
    if not cart:
        flash('Your cart is empty.', 'warning')
        return redirect(url_for('home'))

    cart_items = []
    total = 0
    for product_id, quantity in cart.items():
        product = Product.query.get(int(product_id))
        if product:
            subtotal = product.price * quantity
            total += subtotal
            cart_items.append({'product': product, 'quantity': quantity, 'subtotal': subtotal})

    if request.method == 'POST':
        customer_name = request.form.get('customer_name', '').strip()
        phone = request.form.get('phone', '').strip()
        location = request.form.get('location', '').strip()
        payment_method = request.form.get('payment_method', '').strip()
        
        if not customer_name or not phone or not location or not payment_method:
            flash('Please fill in all delivery details.', 'danger')
            return redirect(url_for('checkout'))
        
        new_order = Order(customer_name=customer_name, phone=phone, location=location, payment_method=payment_method, total_amount=total)
        db.session.add(new_order)
        db.session.flush()

        items_text = ""
        for item in cart_items:
            order_item = OrderItem(order_id=new_order.id, product_id=item['product'].id, quantity=item['quantity'], price=item['product'].price)
            db.session.add(order_item)
            items_text += f"- {item['product'].name} (x{item['quantity']}) = KSh {item['subtotal']:,.2f}%0A"

        db.session.commit()
        session.pop('cart', None)

        message = (
            f"Hello TJ Shop! I want to place an order.%0A%0A"
            f"*Name:* {customer_name}%0A*Phone:* {phone}%0A*Location:* {location}%0A"
            f"*Payment Method:* {payment_method}%0A%0A*ORDER DETAILS:*%0A{items_text}%0A"
            f"*Total:* KSh {total:,.2f}%0A%0APlease send your payment to Pochi: {POCHI_NUMBER}."
        )
        return redirect(f"https://wa.me/{WHATSAPP_NUMBER}?text={message}")
        
    return render_template('checkout.html', cart_items=cart_items, total=total)

# --- Admin Auth Routes ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == ADMIN_PASSWORD:
            session['logged_in'] = True
            flash('Successfully logged in!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Incorrect password. Try again.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('home'))

@app.route('/add', methods=['GET', 'POST'])
def add_product():
    if not session.get('logged_in'):
        flash('You must be logged in to add products.', 'danger')
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip()
        description = request.form.get('description', '').strip()
        price_input = request.form.get('price', '').strip()
        
        if not name or not category:
            flash('Please fill in all required fields.', 'danger')
            return redirect(url_for('add_product'))
        
        try:
            price = float(price_input)
            if price <= 0:
                flash('Price must be a positive number.', 'danger')
                return redirect(url_for('add_product'))
        except (ValueError, TypeError):
            flash('Invalid price. Please enter a valid number (e.g., 4500).', 'danger')
            return redirect(url_for('add_product'))
        
        image = request.files.get('image')
        image_url = ""
        if image and image.filename != '':
            try:
                upload_result = cloudinary.uploader.upload(image)
                image_url = upload_result.get('secure_url')
            except Exception as e:
                print(f"CLOUDINARY ERROR: {e}")
                flash(f'Image upload failed: {e}', 'danger')
                return redirect(url_for('add_product'))
        
        new_product = Product(name=name, price=price, description=description, category=category, image_url=image_url, seller_name="TJ Shop", seller_phone=WHATSAPP_NUMBER, status='Approved')
        db.session.add(new_product)
        db.session.commit()
        flash('Product added successfully!', 'success')
        return redirect(url_for('home'))
    return render_template('add_product.html')

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_product(id):
    if not session.get('logged_in'):
        flash('You must be logged in to edit products.', 'danger')
        return redirect(url_for('login'))
    
    product = Product.query.get_or_404(id)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip()
        description = request.form.get('description', '').strip()
        price_input = request.form.get('price', '').strip()
        
        if not name or not category:
            flash('Please fill in all required fields.', 'danger')
            return redirect(url_for('edit_product', id=id))
        
        try:
            price = float(price_input)
            if price <= 0:
                flash('Price must be a positive number.', 'danger')
                return redirect(url_for('edit_product', id=id))
        except (ValueError, TypeError):
            flash('Invalid price. Please enter a valid number.', 'danger')
            return redirect(url_for('edit_product', id=id))
        
        product.name = name
        product.price = price
        product.description = description
        product.category = category
        
        image = request.files.get('image')
        if image and image.filename != '':
            try:
                upload_result = cloudinary.uploader.upload(image)
                product.image_url = upload_result.get('secure_url')
            except Exception as e:
                print(f"CLOUDINARY ERROR: {e}")
                flash(f'Image upload failed: {e}', 'danger')
                return redirect(url_for('edit_product', id=id))
            
        db.session.commit()
        flash('Product updated successfully!', 'success')
        return redirect(url_for('home'))
    return render_template('edit_product.html', product=product)

@app.route('/delete/<int:id>')
def delete_product(id):
    if not session.get('logged_in'):
        flash('You must be logged in to delete products.', 'danger')
        return redirect(url_for('login'))
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted.', 'success')
    return redirect(url_for('home'))

@app.route('/admin/pending')
def admin_pending():
    if not session.get('logged_in'):
        flash('You must be logged in.', 'danger')
        return redirect(url_for('login'))
    pending_products = Product.query.filter_by(status='Pending').all()
    return render_template('admin_pending.html', products=pending_products)

@app.route('/approve/<int:id>')
def approve_product(id):
    if not session.get('logged_in'):
        flash('You must be logged in.', 'danger')
        return redirect(url_for('login'))
    product = Product.query.get_or_404(id)
    product.status = 'Approved'
    db.session.commit()
    flash(f'{product.name} has been approved!', 'success')
    return redirect(url_for('admin_pending'))

@app.route('/reject/<int:id>')
def reject_product(id):
    if not session.get('logged_in'):
        flash('You must be logged in.', 'danger')
        return redirect(url_for('login'))
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    flash('Product rejected and deleted.', 'info')
    return redirect(url_for('admin_pending'))

@app.route('/admin/orders')
def admin_orders():
    if not session.get('logged_in'):
        flash('You must be logged in to view orders.', 'danger')
        return redirect(url_for('login'))
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template('admin_orders.html', orders=orders)

@app.route('/admin/order/<int:order_id>/status/<string:new_status>')
def update_order_status(order_id, new_status):
    if not session.get('logged_in'):
        flash('You must be logged in.', 'danger')
        return redirect(url_for('login'))
    
    order = Order.query.get_or_404(order_id)
    if new_status in ['Pending', 'Shipped', 'Delivered']:
        order.status = new_status
        db.session.commit()
        flash(f'Order #{order.id} status updated to {new_status}.', 'success')
    return redirect(url_for('admin_orders'))

# --- NEW ADMIN SUBSCRIPTION ROUTES ---
@app.route('/admin/subscriptions')
def admin_subscriptions():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    pending_subs = Subscription.query.filter_by(status='Pending').all()
    return render_template('admin_subscriptions.html', subscriptions=pending_subs)

@app.route('/admin/approve_subscription/<int:id>')
def approve_subscription(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    sub = Subscription.query.get_or_404(id)
    
    # 1. Expire any old active plans for this user
    old_subs = Subscription.query.filter_by(user_id=sub.user_id, status='Active').all()
    for old in old_subs:
        old.status = 'Expired'
        
    # 2. Activate the new plan
    sub.status = 'Active'
    sub.start_date = datetime.utcnow()
    sub.expiry_date = datetime.utcnow() + timedelta(days=30) # 30 days subscription
    db.session.commit()
    
    flash(f'Subscription approved for {sub.user.name}!', 'success')
    return redirect(url_for('admin_subscriptions'))

@app.route('/admin/reject_subscription/<int:id>')
def reject_subscription(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    sub = Subscription.query.get_or_404(id)
    sub.status = 'Rejected'
    db.session.commit()
    
    flash('Subscription rejected.', 'info')
    return redirect(url_for('admin_subscriptions'))

if __name__ == '__main__':
    app.run(debug=True)