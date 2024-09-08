from flask import Flask, render_template, request, jsonify
import sqlite3

app = Flask(__name__)

def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/products')
def products():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page
    
    conn = get_db_connection()
    products = conn.execute('SELECT * FROM products LIMIT ? OFFSET ?', 
                            (per_page, offset)).fetchall()
    conn.close()
    
    return render_template('products.html', products=products, page=page)

if __name__ == '__main__':
    app.run(debug=True)