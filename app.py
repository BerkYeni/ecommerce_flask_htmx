from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from flask import flash
from math import ceil
from collections import Counter
from functools import wraps
from flask_mail import Mail, Message

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Set a secret key for session management

app.config['MAIL_SERVER'] = 'smtp.example.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'your-email@example.com'
app.config['MAIL_PASSWORD'] = 'your-email-password'
app.config['MAIL_DEFAULT_SENDER'] = 'your-email@example.com'

mail = Mail(app)

def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def get_product_recommendations(user_id, limit=4):
    conn = get_db_connection()
    # Get products from user's order history
    ordered_products = conn.execute('''
        SELECT DISTINCT oi.product_id
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.id
        WHERE o.user_id = ?
    ''', (user_id,)).fetchall()
    
    ordered_product_ids = [p['product_id'] for p in ordered_products]
    
    if not ordered_product_ids:
        # If user has no order history, return top-selling products
        recommendations = conn.execute('''
            SELECT p.*, COUNT(oi.id) as order_count
            FROM products p
            LEFT JOIN order_items oi ON p.id = oi.product_id
            GROUP BY p.id
            ORDER BY order_count DESC
            LIMIT ?
        ''', (limit,)).fetchall()
    else:
        # Get products that are often bought together with the user's purchased products
        related_products = conn.execute('''
            SELECT oi2.product_id, COUNT(*) as frequency
            FROM order_items oi1
            JOIN order_items oi2 ON oi1.order_id = oi2.order_id
            WHERE oi1.product_id IN ({})
            AND oi2.product_id NOT IN ({})
            GROUP BY oi2.product_id
            ORDER BY frequency DESC
            LIMIT ?
        '''.format(','.join('?' * len(ordered_product_ids)), ','.join('?' * len(ordered_product_ids))),
        (*ordered_product_ids, *ordered_product_ids, limit)).fetchall()
        
        recommendation_ids = [p['product_id'] for p in related_products]
        recommendations = conn.execute('SELECT * FROM products WHERE id IN ({})'.format(','.join('?' * len(recommendation_ids))),
                                       recommendation_ids).fetchall()
    
    conn.close()
    return recommendations

@app.route('/')
def index():
    recommendations = []
    if 'user_id' in session:
        recommendations = get_product_recommendations(session['user_id'])
    return render_template('index.html', recommendations=recommendations)

@app.route('/products')
def products():
    page = request.args.get('page', 1, type=int)
    per_page = 12  # Increased from 10 to 12 for better grid layout
    
    conn = get_db_connection()
    total_products = conn.execute('SELECT COUNT(*) FROM products').fetchone()[0]
    total_pages = ceil(total_products / per_page)
    
    offset = (page - 1) * per_page
    products = conn.execute('SELECT * FROM products LIMIT ? OFFSET ?', 
                            (per_page, offset)).fetchall()
    conn.close()
    
    return render_template('products.html', products=products, page=page, total_pages=total_pages)

@app.route('/add-to-cart/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    if 'cart' not in session:
        session['cart'] = {}
    
    cart = session['cart']
    cart[str(product_id)] = cart.get(str(product_id), 0) + 1
    session.modified = True
    
    return str(sum(cart.values())), 200

@app.route('/cart')
def view_cart():
    cart = session.get('cart', {})
    
    if not cart:
        return render_template('cart.html', cart_items=[])
    
    conn = get_db_connection()
    cart_items = []
    total = 0
    
    for product_id, quantity in cart.items():
        product = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
        if product:
            item_total = product['price'] * quantity
            cart_items.append({
                'id': product['id'],
                'name': product['name'],
                'price': product['price'],
                'quantity': quantity,
                'total': item_total
            })
            total += item_total
    
    conn.close()
    return render_template('cart.html', cart_items=cart_items, total=total)

@app.route('/update-cart/<int:product_id>', methods=['POST'])
def update_cart(product_id):
    cart = session.get('cart', {})
    quantity = int(request.form.get('quantity', 0))
    
    if quantity > 0:
        cart[str(product_id)] = quantity
    else:
        cart.pop(str(product_id), None)
    
    session['cart'] = cart
    session.modified = True
    
    return redirect(url_for('view_cart'))

@app.route('/remove-from-cart/<int:product_id>', methods=['POST'])
def remove_from_cart(product_id):
    cart = session.get('cart', {})
    cart.pop(str(product_id), None)
    session['cart'] = cart
    session.modified = True
    
    return redirect(url_for('view_cart'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        
        if user:
            return 'Username already exists', 400
        
        conn.execute('INSERT INTO users (username, password) VALUES (?, ?)',
                     (username, generate_password_hash(password)))
        conn.commit()
        conn.close()
        
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            return redirect(url_for('index'))
        
        return 'Invalid username or password', 401
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('index'))

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        # Process the order
        cart = session.get('cart', {})
        user_id = session['user_id']
        
        conn = get_db_connection()
        
        # Create an order
        cur = conn.cursor()
        cur.execute('INSERT INTO orders (user_id, status) VALUES (?, ?)', (user_id, 'pending'))
        order_id = cur.lastrowid
        
        # Add order items
        for product_id, quantity in cart.items():
            cur.execute('INSERT INTO order_items (order_id, product_id, quantity) VALUES (?, ?, ?)',
                        (order_id, product_id, quantity))
        
        # Get user email
        user = conn.execute('SELECT email FROM users WHERE id = ?', (user_id,)).fetchone()
        
        conn.commit()
        conn.close()
        
        # Send order confirmation email
        send_order_confirmation_email(order_id, user['email'])
        
        # Clear the cart
        session.pop('cart', None)
        
        flash('Your order has been placed successfully!', 'success')
        return redirect(url_for('order_confirmation', order_id=order_id))
    
    return render_template('checkout.html')

def send_order_confirmation_email(order_id, user_email):
    msg = Message('Order Confirmation', recipients=[user_email])
    msg.body = f'Thank you for your order! Your order number is: {order_id}'
    mail.send(msg)

@app.route('/order-confirmation/<int:order_id>')
def order_confirmation(order_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    order_items = conn.execute('''
        SELECT oi.quantity, p.name, p.price
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id = ?
    ''', (order_id,)).fetchall()
    conn.close()
    
    return render_template('order_confirmation.html', order=order, order_items=order_items)

@app.route('/search')
def search():
    query = request.args.get('q', '')
    conn = get_db_connection()
    products = conn.execute('SELECT * FROM products WHERE name LIKE ? OR description LIKE ?',
                            (f'%{query}%', f'%{query}%')).fetchall()
    conn.close()
    return render_template('search_results.html', products=products, query=query)

@app.route('/product/<int:product_id>')
def product_detail(product_id):
    conn = get_db_connection()
    product = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
    reviews = conn.execute('SELECT * FROM reviews WHERE product_id = ? ORDER BY created_at DESC', (product_id,)).fetchall()
    conn.close()
    return render_template('product_detail.html', product=product, reviews=reviews)

@app.route('/add_review/<int:product_id>', methods=['POST'])
def add_review(product_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    rating = int(request.form['rating'])
    comment = request.form['comment']
    user_id = session['user_id']
    
    conn = get_db_connection()
    conn.execute('INSERT INTO reviews (user_id, product_id, rating, comment) VALUES (?, ?, ?, ?)',
                 (user_id, product_id, rating, comment))
    conn.commit()
    conn.close()
    
    flash('Your review has been added successfully!', 'success')
    return redirect(url_for('product_detail', product_id=product_id))

@app.route('/wishlist')
def wishlist():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    wishlist_items = conn.execute('''
        SELECT p.* FROM products p
        JOIN wishlist w ON p.id = w.product_id
        WHERE w.user_id = ?
    ''', (session['user_id'],)).fetchall()
    conn.close()
    
    return render_template('wishlist.html', wishlist_items=wishlist_items)

@app.route('/add_to_wishlist/<int:product_id>', methods=['POST'])
def add_to_wishlist(product_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    conn.execute('INSERT OR IGNORE INTO wishlist (user_id, product_id) VALUES (?, ?)',
                 (session['user_id'], product_id))
    conn.commit()
    conn.close()
    
    flash('Product added to your wishlist!', 'success')
    return redirect(url_for('product_detail', product_id=product_id))

@app.route('/remove_from_wishlist/<int:product_id>', methods=['POST'])
def remove_from_wishlist(product_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    conn.execute('DELETE FROM wishlist WHERE user_id = ? AND product_id = ?',
                 (session['user_id'], product_id))
    conn.commit()
    conn.close()
    
    flash('Product removed from your wishlist!', 'success')
    return redirect(url_for('wishlist'))

@app.route('/order_history')
def order_history():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    orders = conn.execute('''
        SELECT o.id, o.created_at, o.status, SUM(p.price * oi.quantity) as total
        FROM orders o
        JOIN order_items oi ON o.id = oi.order_id
        JOIN products p ON oi.product_id = p.id
        WHERE o.user_id = ?
        GROUP BY o.id
        ORDER BY o.created_at DESC
    ''', (session['user_id'],)).fetchall()
    conn.close()
    
    return render_template('order_history.html', orders=orders)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        conn.close()
        
        if not user or not user['is_admin']:
            flash('You do not have permission to access this page.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin')
@admin_required
def admin_dashboard():
    conn = get_db_connection()
    products = conn.execute('SELECT * FROM products').fetchall()
    users = conn.execute('SELECT * FROM users').fetchall()
    orders = conn.execute('SELECT * FROM orders').fetchall()
    conn.close()
    return render_template('admin/dashboard.html', products=products, users=users, orders=orders)

@app.route('/admin/products')
@admin_required
def admin_products():
    conn = get_db_connection()
    products = conn.execute('SELECT * FROM products').fetchall()
    conn.close()
    return render_template('admin/products.html', products=products)

@app.route('/admin/products/add', methods=['GET', 'POST'])
@admin_required
def admin_add_product():
    if request.method == 'POST':
        name = request.form['name']
        price = float(request.form['price'])
        description = request.form['description']
        
        conn = get_db_connection()
        conn.execute('INSERT INTO products (name, price, description) VALUES (?, ?, ?)',
                     (name, price, description))
        conn.commit()
        conn.close()
        
        flash('Product added successfully!', 'success')
        return redirect(url_for('admin_products'))
    
    return render_template('admin/add_product.html')

@app.route('/admin/products/edit/<int:product_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_product(product_id):
    conn = get_db_connection()
    product = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
    
    if request.method == 'POST':
        name = request.form['name']
        price = float(request.form['price'])
        description = request.form['description']
        
        conn.execute('UPDATE products SET name = ?, price = ?, description = ? WHERE id = ?',
                     (name, price, description, product_id))
        conn.commit()
        conn.close()
        
        flash('Product updated successfully!', 'success')
        return redirect(url_for('admin_products'))
    
    conn.close()
    return render_template('admin/edit_product.html', product=product)

@app.route('/admin/products/delete/<int:product_id>', methods=['POST'])
@admin_required
def admin_delete_product(product_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM products WHERE id = ?', (product_id,))
    conn.commit()
    conn.close()
    
    flash('Product deleted successfully!', 'success')
    return redirect(url_for('admin_products'))

if __name__ == '__main__':
    app.run(debug=True)