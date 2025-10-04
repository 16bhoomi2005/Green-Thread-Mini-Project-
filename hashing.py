from werkzeug.security import generate_password_hash
import sqlite3

# Connect to the database
conn = sqlite3.connect('carbon_footprint_db.db')
cursor = conn.cursor()

# Drop and recreate the admins table
cursor.execute("DROP TABLE IF EXISTS admins")
cursor.execute("""
    CREATE TABLE admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )
""")

# Insert admin with hashed password
admin_username = "admin1"
plain_password = "admin1"
hashed_password = generate_password_hash(plain_password)
cursor.execute("INSERT INTO admins (username, password) VALUES (?, ?)", (admin_username, hashed_password))

conn.commit()
conn.close()

print("Admin table reinitialized and password hashed successfully!")