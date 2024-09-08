import sqlite3

connection = sqlite3.connect('database.db')

with open('schema.sql') as f:
    connection.executescript(f.read())

cur = connection.cursor()

# Add some sample products
cur.execute("INSERT INTO products (name, price, description) VALUES (?, ?, ?)",
            ('Product 1', 19.99, 'Description for Product 1')
            )

cur.execute("INSERT INTO products (name, price, description) VALUES (?, ?, ?)",
            ('Product 2', 29.99, 'Description for Product 2')
            )

connection.commit()
connection.close()