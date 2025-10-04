from flask import Flask, request, jsonify, render_template, send_file, session, redirect, url_for, after_this_request
import sqlite3
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
import numpy as np
from io import BytesIO
import logging
from werkzeug.security import generate_password_hash, check_password_hash
import re
import pytz
import glob
import tempfile
import shutil

app = Flask(__name__)
app.secret_key = "your_secret_key"  # Required for session management

# Ensure the static/graphs directory exists
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GRAPH_DIR = os.path.join(BASE_DIR, "static/graphs")
os.makedirs(GRAPH_DIR, exist_ok=True)

# Function to connect to SQLite
def get_db_connection():
    conn = sqlite3.connect('carbon_footprint_db.db')
    conn.row_factory = sqlite3.Row  # Enables column access by name
    return conn

# Initialize the database: create the 'users' table if it doesn't exist.
@app.route('/init-db')
def init_db():
    conn = get_db_connection()
    try:
        conn.execute("PRAGMA foreign_keys = ON;")  # Enable foreign key support

        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT NOT NULL,
                password TEXT NOT NULL,
                credit_points INTEGER DEFAULT 0
                     
            )
        ''')
        conn.execute('''
    CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    );


''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material TEXT NOT NULL,
                description TEXT,
                material_footprint REAL DEFAULT 1.0,
                             biodegradability TEXT,
                             recyclability TEXT,
                             eco_rating TEXT CHECK(eco_rating IN ('Eco-Friendly', 'Moderate', 'High Impact'))


                     
            )
        ''')
        conn.execute('''
    CREATE TABLE IF NOT EXISTS challenges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        credit_points INTEGER NOT NULL
    )
''')

        conn.execute('''
        CREATE TABLE IF NOT EXISTS user_challenges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        challenge_id INTEGER NOT NULL,
        is_completed BOOLEAN DEFAULT FALSE,
        completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
        FOREIGN KEY (username) REFERENCES users(username),
        FOREIGN KEY (challenge_id) REFERENCES challenges(id)
        

    )
''')
        # Create the 'brands' table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS brands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT
            )
        ''')
        conn.execute('''CREATE TABLE IF NOT EXISTS progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    week INTEGER NOT NULL,
    total_emission REAL NOT NULL,
    best_day TEXT NOT NULL,
    best_day_emission REAL NOT NULL,
    worst_day TEXT NOT NULL,
    worst_day_emission REAL NOT NULL,
    streak INTEGER DEFAULT 0,
    reduced_emission BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (username) REFERENCES users(username)
);
''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS carbon_footprint (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                material TEXT,
                washing_frequency TEXT,
                drying_method TEXT,
                ironing_frequency TEXT,
                weight REAL,
                footprint REAL,
                is_wearing_today INTEGER DEFAULT 0,

                FOREIGN KEY (username) REFERENCES users (username)
            )
        ''')
        conn.commit()
        return "Database and table initialized!"
    except Exception as e:
        app.logger.error(f"Error initializing database: {str(e)}")
        return f"Error initializing database: {str(e)}", 500
    finally:
        conn.close()
def get_ist_time():
    ist = pytz.timezone('Asia/Kolkata')
    return datetime.now(ist).strftime('%Y-%m-%d')

# -------------------- Routes --------------------


@app.route('/admin_login', methods=['POST'])
def admin_login():
    data = request.get_json()  # Get JSON data
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"message": "Username and password required!"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, password FROM admins WHERE username=?", (username,))
    admin = cursor.fetchone()
    conn.close()

    if admin:
        app.logger.info(f"Admin found: {admin}")
    else:
        app.logger.info("Admin not found!")

    if admin and check_password_hash(admin['password'], password):
        session['admin'] = username  # Store admin session
        return jsonify({"message": "Admin login successful!"}), 200
    else:
        return jsonify({"message": "Invalid admin credentials!"}), 401

 # Replace with admin dashboard page
@app.route('/admin_login')
def admin_login_page():
    return render_template('admin_login.html')
@app.route('/')
def home():
    return render_template('home.html')
@app.route('/index')
def index():
    return render_template('index.html')
@app.route('/startup')
def startup():
    return render_template("startup.html")
@app.route('/brand')
def brand():
    return render_template("brand.html")
@app.route('/about')
def about():
    return render_template("about.html")

def create_admins_table():
    conn = sqlite3.connect("carbon_footprint_db.db")  # Ensure you're using the correct database file
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)
    
    conn.commit()
    conn.close()
    print("✅ Admins table created successfully!")
create_admins_table()

@app.route('/admin')
def admin_dashboard():
    if 'admin' not in session:
        return redirect(url_for('admin_login_page'))  # Redirect if not logged in

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get the number of users
    cursor.execute("SELECT COUNT(*) FROM users")
    user_count = cursor.fetchone()[0]

    # Get the number of carbon footprint records
    cursor.execute("SELECT COUNT(*) FROM carbon_footprint")
    record_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM materials")
    clothing_count = cursor.fetchone()[0]


    cursor.execute("SELECT AVG(footprint) FROM carbon_footprint")
    avg_footprint = cursor.fetchone()[0] or 0

    return render_template('admin.html',
                               user_count=user_count,
                               record_count=record_count,
                               clothing_count=clothing_count,
                               avg_footprint=round(avg_footprint, 2))

@app.route('/admin/users', methods=['GET'])
def manage_users():
    if 'admin' not in session:
        return redirect(url_for('admin_login_page'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, credit_points, username, email FROM users")
    users = cursor.fetchall()
    conn.close()

    return render_template('manage_users.html', users=users)

@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if 'admin' not in session:
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()

    # Return a success response
    return jsonify({"message": "User deleted successfully!"}), 200
    
@app.route('/admin/challenges', methods=['GET', 'POST'])
def manage_challenges():
    if 'admin' not in session:
        return redirect(url_for('admin_login_page'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if request.method == 'POST':
            # Add a new challenge
            title = request.form.get('title')
            description = request.form.get('description')
            credit_points = request.form.get('credit_points')

            if not title or not description or not credit_points:
                return jsonify({"error": "All fields are required"}), 400

            cursor.execute("""
                INSERT INTO challenges (title, description, credit_points)
                VALUES (?, ?, ?)
            """, (title, description, credit_points))
            conn.commit()

        # Fetch all challenges
        cursor.execute("SELECT * FROM challenges")
        challenges = cursor.fetchall()

    except Exception as e:
        app.logger.error(f"Error managing challenges: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

    return render_template('manage_challenges.html', challenges=challenges)


@app.route('/admin/challenges/update/<int:challenge_id>', methods=['POST'])
def update_challenge(challenge_id):
    if 'admin' not in session:
        return jsonify({"message": "Unauthorized"}), 401

    title = request.form.get('title')
    description = request.form.get('description')
    credit_points = request.form.get('credit_points')

    if not title or not description or not credit_points:
        return jsonify({"error": "All fields are required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE challenges
            SET title = ?, description = ?, credit_points = ?
            WHERE id = ?
        """, (title, description, credit_points, challenge_id))
        conn.commit()
        return jsonify({"message": "Challenge updated successfully!"}), 200
    except Exception as e:
        app.logger.error(f"Error updating challenge: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/admin/challenges/delete/<int:challenge_id>', methods=['POST'])
def delete_challenge(challenge_id):
    if 'admin' not in session:
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM challenges WHERE id = ?", (challenge_id,))
        conn.commit()
        return jsonify({"message": "Challenge deleted successfully!"}), 200
    except Exception as e:
        app.logger.error(f"Error deleting challenge: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/admin/clothing', methods=['GET', 'POST'])
def manage_clothing():
    if 'admin' not in session:
        return redirect(url_for('admin_login_page'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if request.method == 'POST':
            material = request.form.get('material')
            description = request.form.get('description')
            average_footprint = request.form.get('average_footprint', 1.0)
            biodegradability= request.form.get('biodegradability')
            recyclability= request.form.get('recyclability')
            eco_rating=request.form.get('eco_rating')

            # Log the incoming data
            app.logger.debug(f"Material: {material}, Description: {description}, Average Footprint: {average_footprint}")

            # Validate form data
            if not material or not description:
                return jsonify({"error": "Material and description are required!"}), 400

            # Convert average_footprint to float
            try:
                average_footprint = float(average_footprint)
            except ValueError:
                return jsonify({"error": "Invalid average footprint value!"}), 400

            # Insert the material into the database
            cursor.execute(
                "INSERT INTO materials (material, description, material_footprint,biodegradability,recyclability,eco_rating) VALUES (?, ?, ?,?,?,?)",
                (material, description, average_footprint,biodegradability,recyclability,eco_rating)
            )
            conn.commit()

        # Fetch all materials
        cursor.execute("SELECT * FROM materials")
        materials = cursor.fetchall()

    except sqlite3.IntegrityError as e:
        app.logger.error(f"Database Integrity Error: {str(e)}")
        return jsonify({"error": "Material already exists!"}), 400
    except Exception as e:
        app.logger.error(f"Error in manage_clothing: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

    return render_template('manage_clothing.html', materials=materials)

@app.route('/admin/clothing/update/<int:material_id>', methods=['POST'])
def update_clothing(material_id):
    logging.info(f"Updating material with ID: {material_id}")
    material = request.form.get('material')
    description = request.form.get('description')
    material_footprint = request.form.get('material_footprint')
    biodegradability= request.form.get('biodegradability')
    recyclabilty = request.form.get('recyclabilty')
    rating= request.form.get('eco_rating')


    logging.info(f"Received data - Material: {material}, Description: {description}")
    
    if 'admin' not in session:
        return jsonify({"message": "Unauthorized"}), 401

    material = request.form.get('material')
    description = request.form.get('description')

    if not material or not description:
        return jsonify({"message": "Material and description are required!"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    biodegradability= request.form.get('biodegradability')
    cursor.execute("""
            UPDATE materials
            SET material = ?, description = ?, material_footprint = ?, biodegradability = ?, recyclability = ?, eco_rating = ?
            WHERE id = ?""", (material, description, material_footprint, biodegradability, recyclabilty, rating, material_id))
    conn.commit()
    conn.close()

    return jsonify({"message": "Material updated successfully!"}), 200

@app.route('/admin/clothing/delete/<int:material_id>', methods=['POST'])
def delete_clothing(material_id):
    if 'admin' not in session:
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM materials WHERE id=?", (material_id,))
    conn.commit()
    conn.close()

    return jsonify({"message": "Material deleted successfully!"}), 200
@app.route('/admin/carbon-footprint', methods=['GET'])
def manage_carbon_footprint():
    if 'admin' not in session:
        return redirect(url_for('admin_login_page'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM carbon_footprint")
    records = cursor.fetchall()
    conn.close()

    return render_template('manage_carbon_footprint.html', records=records)

@app.route('/admin/carbon-footprint/delete/<int:record_id>', methods=['POST'])
def delete_carbon_footprint(record_id):
    if 'admin' not in session:
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM carbon_footprint WHERE id=?", (record_id,))
    conn.commit()
    conn.close()

    return jsonify({"message": "Record deleted successfully!"}), 200
@app.route('/admin/carbon-footprint/update/<int:record_id>', methods=['POST'])
def update_carbon_footprint(record_id):
    if 'admin' not in session:
        return jsonify({"message": "Unauthorized"}), 401

    material = request.form.get('material')
    washing_frequency = request.form.get('washing_frequency')
    drying_method = request.form.get('drying_method')
    ironing_frequency = request.form.get('ironing_frequency')
    weight = float(request.form.get('weight', 0) or 0)

    if not material or not washing_frequency or not drying_method or not ironing_frequency:
        return jsonify({"message": "All fields are required!"}), 400

    # Recalculate the carbon footprint
    base_emission_factors = {'cotton': 1.0, 'polyester': 1.5, 'wool': 1.2, 'silk': 2.5}
    washing_modifiers = {"Daily": 1.5, "Weekly": 1.0, "Monthly": 0.5}
    drying_modifiers = {"Machine": 1.3, "Air": 0.7}
    ironing_modifiers = {"Rarely": 0.5, "Often": 1.0}

    base_emission = base_emission_factors.get(material.lower(), 1.0)
    washing_modifier = washing_modifiers.get(washing_frequency.capitalize(), 1.0)
    drying_modifier = drying_modifiers.get(drying_method, 1.0)
    ironing_modifier = ironing_modifiers.get(ironing_frequency, 0.5)

    carbon_footprint = base_emission * washing_modifier * drying_modifier * ironing_modifier
    if weight > 0:
        carbon_footprint *= weight * 0.1

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE carbon_footprint
        SET material = ?, washing_frequency = ?, drying_method = ?, ironing_frequency = ?, weight = ?, footprint = ?
        WHERE id = ?
    """, (material, washing_frequency, drying_method, ironing_frequency, weight, carbon_footprint, record_id))
    conn.commit()
    conn.close()

    return jsonify({"message": "Record updated successfully!"}), 200
@app.route('/admin/add-challenge', methods=['POST'])
def add_challenge():
    if 'admin' not in session:
        return redirect(url_for('admin_login_page'))

    title = request.form.get('title')
    description = request.form.get('description')
    credit_points = request.form.get('credit_points')

    if not title or not description or not credit_points:
        return jsonify({"error": "All fields are required"}), 400

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO challenges (title, description, credit_points)
            VALUES (?, ?, ?)
        """, (title, description, credit_points))
        conn.commit()
        return jsonify({"message": "Challenge added successfully"}), 201
    except Exception as e:
        app.logger.error(f"Error adding challenge: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/admin/analytics', methods=['GET'])
def analytics():
    if 'admin' not in session:
        return redirect(url_for('admin_login_page'))

    conn = get_db_connection()
    cursor = conn.cursor()

    # Example: Total users and total carbon footprint
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(footprint) FROM carbon_footprint")
    total_footprint = cursor.fetchone()[0] or 0

    conn.close()

    return render_template('analytics.html', total_users=total_users, total_footprint=total_footprint)


@app.route('/calculator')
def calculator():
    if 'user' not in session:
        return redirect(url_for('login'))  # Redirect to login if not logged in

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT material FROM materials")
    materials = cursor.fetchall()
    conn.close()

    return render_template('calculator.html', materials=materials)

def cleanup_old_graphs(username):
    """
    Delete old graph files for a specific user.
    """
    graph_dir = os.path.join(app.static_folder, 'graphs')
    # Find all graph files for the user
    user_graphs = glob.glob(os.path.join(graph_dir, f"{username}_*.png"))
    # Delete the files
    for graph_file in user_graphs:
        try:
            os.remove(graph_file)
            app.logger.info(f"Deleted old graph file: {graph_file}")
        except Exception as e:
            app.logger.error(f"Error deleting graph file {graph_file}: {str(e)}")


def is_valid_email(email):
    """Validate email format using a simple regex."""
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return re.match(pattern, email) is not None

@app.route('/register', methods=['POST'])
def register():
    conn = None
    try:
        data = request.get_json()  # Now Flask expects JSON
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        confirm_password = data.get('confirm_password')

        if not username or not email or not password or not confirm_password:
            return jsonify({"message": "Missing fields"}), 400
        if password != confirm_password:
            return jsonify({"message": "Passwords do not match"}), 400
        if len(password) < 6:
            return jsonify({"message": "Password must be at least 6 characters long"}), 400
        if not is_valid_email(email):
            return jsonify({"message": "Invalid email format"}), 400
        hashed_password = generate_password_hash(password)  # Hash the password

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)", (username.strip(), email.strip(), hashed_password))
        app.logger.info(f"User registered: {username}")

        conn.commit()
        app.logger.info(f"User registered: {username}")
        return jsonify({"message": "Registration successful!"}), 200
    except sqlite3.IntegrityError:
        return jsonify({"message": "Username or email already exists!"}), 400
    except Exception as e:
        app.logger.error(f"Error: {str(e)}")
        return jsonify({"message": f"Error: {str(e)}"}), 500
    finally:
        if conn:
            conn.close()

@app.route('/admin-logout')
def admin_logout():
    session.pop('admin', None)  # Remove the admin from the session
    return jsonify({"message": "Admin logged out successfully!"}), 200

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password or len(password) < 6:

        return jsonify({"message": "Username and password are required!"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username=?", (username,))
    user = cursor.fetchone()
    conn.close()

    if user and check_password_hash(user['password'], password):  # Password is in the 4th column (index 3)

        session['user'] = username  # Store the logged-in user in the session
        return jsonify({"message": "Login successful!", "username": username}), 200
    else:
        return jsonify({"message": "Invalid credentials!"}), 401
        
@app.route('/logout')
def logout():
    session.pop('user', None)  # Remove the user from the session
    session.clear()  # Clear all session data
    return jsonify({"message": "Logged out successfully!"}), 200
@app.route('/current_user', methods=['GET'])
def current_user():
    username = session.get('user')

    if 'user' in session:
        return jsonify({"username": session['user']}), 200
    return jsonify({"message": "No user logged in"}), 400

@app.route('/challenges')
def challenges():
    if 'user' not in session:
        return redirect(url_for('login'))

    username = session['user']
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.id, c.title, c.description, c.credit_points,
                   COUNT(uc.id) AS completion_count
            FROM challenges c
            LEFT JOIN user_challenges uc
            ON c.id = uc.challenge_id AND uc.username = ?
            GROUP BY c.id
        """, (username,))
        challenges = cursor.fetchall()
        return render_template('challenges.html', challenges=challenges)
    except Exception as e:
        app.logger.error(f"Error fetching challenges: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/complete-challenge/<int:challenge_id>', methods=['POST'])
def complete_challenge(challenge_id):
    if 'user' not in session:
        return jsonify({"error": "User not logged in"}), 401

    username = session['user']
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Check if the challenge exists and get its credit points
        cursor.execute("""
            SELECT credit_points FROM challenges WHERE id = ?
        """, (challenge_id,))
        challenge = cursor.fetchone()
        
        if not challenge:
            return jsonify({"error": "Challenge not found"}), 404

        # Insert a new record for the challenge completion
        cursor.execute("""
            INSERT INTO user_challenges (username, challenge_id, is_completed)
            VALUES (?, ?, TRUE)
        """, (username, challenge_id))

        # Update user's credit points
        cursor.execute("""
            UPDATE users SET credit_points = credit_points + ?
            WHERE username = ?
        """, (challenge['credit_points'], username))

        conn.commit()
        return jsonify({
            "message": "Challenge completed successfully",
            "completed": True,
            "credit_points": challenge['credit_points']
        }), 200
        
    except Exception as e:
        conn.rollback()
        app.logger.error(f"Error completing challenge: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/calculate', methods=['POST'])
def calculate():
    if 'user' not in session:
        return jsonify({"message": "User not logged in"}), 401

    data = request.form
    app.logger.debug(f"Incoming data: {data}")  # Log the incoming data

    # Validate required fields
    if not data.get('material') or not data.get('drying_method') or not data.get('washing_frequency') or not data.get('is_wearing_today'):
        app.logger.error("Missing required fields")
        return jsonify({"error": "Missing required fields: material, drying_method, washing_frequency, or is_wearing_today"}), 400

    material = data.get('material')
    drying_method = data.get('drying_method')
    washing_frequency = data.get('washing_frequency')
    ironing_frequency = data.get('ironing_frequency', 'Rarely')
    weight = float(data.get('weight', 0) or 0)
    is_wearing_today = data.get('is_wearing_today', 'no').lower()
    is_wearing_today = 1 if is_wearing_today == 'yes' else 0

    # Debugging: print the received data
    app.logger.debug(f"is_wearing_today: {is_wearing_today}")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Fetch the material footprint from the database
        cursor.execute("SELECT material_footprint FROM materials WHERE material = ?", (material,))
        result = cursor.fetchone()
        if not result:
            return jsonify({"error": f"Material '{material}' not found in the database"}), 400

        base_emission = result['material_footprint']

        # Define modifiers
        washing_modifiers = {
            "Daily": 1.5,
            "Weekly": 1.0,
            "Monthly": 0.5
        }
        drying_modifiers = {
            "Machine": 1.3,
            "Air": 0.7
        }
        ironing_modifiers = {
            "Rarely": 0.5,
            "Often": 1.0
        }

        # Calculate the carbon footprint
        washing_modifier = washing_modifiers.get(washing_frequency.capitalize(), 1.0)
        drying_modifier = drying_modifiers.get(drying_method, 1.0)
        ironing_modifier = ironing_modifiers.get(ironing_frequency, 0.5)

        carbon_footprint = base_emission * washing_modifier * drying_modifier * ironing_modifier
        if weight > 0:
            carbon_footprint *= weight * 0.1  # Example: weight factor (you can adjust this formula)

        app.logger.debug(f"Material: {material}, Base Emission: {base_emission}")
        app.logger.debug(f"Washing Modifier: {washing_modifier}, Drying Modifier: {drying_modifier}, Ironing Modifier: {ironing_modifier}")
        app.logger.debug(f"Weight: {weight}, Carbon Footprint: {carbon_footprint}")

        # Save the record if the user is wearing the material today
        if is_wearing_today == 1:
            cursor.execute("""
                INSERT INTO carbon_footprint (username, date, material, washing_frequency, drying_method, ironing_frequency, weight, footprint, is_wearing_today)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (session['user'], get_ist_time(), material, washing_frequency, drying_method, ironing_frequency, weight, carbon_footprint, is_wearing_today))
            conn.commit()

            app.logger.info(f"Record saved for user: {session['user']}")

        return jsonify({
            "message": "Calculation Successful",
            "carbon_footprint": f"{carbon_footprint:.2f} kg of CO2"
        }), 200

    except Exception as e:
        app.logger.error(f"Database Error: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
@app.route('/user_data', methods=['GET'])
def user_data():
    user = session.get('user')  # Get the logged-in user from the session

    if not user:
        return jsonify({'error': 'User not logged in'}), 401  # Unauthorized response
    
    conn = None  # Initialize connection variable

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Execute query using the session user
        cursor.execute("SELECT COALESCE(SUM(footprint), 0), COALESCE(AVG(footprint), 0) FROM carbon_footprint WHERE username=?", (user,))
        result = cursor.fetchone()
        total, avg = result if result else (0, 0)

        return render_template('user-data.html', username=user, total_emission=total or 0, avg_emission=avg or 0)
    
    except Exception as e:
        app.logger.error(f"Error: {str(e)}")
        return jsonify({'error': str(e)}), 500  # Return error as JSON
    
    finally:
        if conn:
            conn.close()  # Close connection only if it was opened


@app.route('/user-graph/<username>')
def user_graph(username):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT date, footprint, is_wearing_today
            FROM carbon_footprint
            WHERE username=? AND is_wearing_today=1
            ORDER BY date
        """, (username,))
        data = cursor.fetchall()

        if not data:
            return render_template('error.html', message="No data available for this user."), 404

        # Extract data from the query result
        dates = [row['date'] for row in data]
        emissions = [row['footprint'] for row in data]
        wearing_today = [row['is_wearing_today'] for row in data]

        # Plot the carbon footprint over time
        plt.figure(figsize=(8, 4))
        plt.plot(dates, emissions, marker='o', linestyle='-', color='b', label='Carbon Footprint')

        # Plot points only if the user is wearing the item today
        if any(wearing_today):
            plt.scatter(
                [date for date, wt in zip(dates, wearing_today) if wt],
                [em for em, wt in zip(emissions, wearing_today) if wt],
                color='r', label='Wearing Today'
            )

        # Customize the graph
        plt.xlabel("Date")
        plt.ylabel("Carbon Footprint")
        plt.title(f"{username}'s Carbon Footprint Over Time")
        plt.xticks(rotation=45)
        plt.legend()
        plt.tight_layout()

        # Ensure the 'static/graphs' directory exists
        graph_dir = os.path.join(tempfile.gettempdir(), 'graphs')
        os.makedirs(graph_dir, exist_ok=True)

        # Save the graph to a file
        graph_path = os.path.join(graph_dir, f"{username}_graph.png")
        plt.savefig(graph_path)
        plt.close()
        app.logger.info(f"Graph saved at: {graph_path}")
        if os.path.exists(graph_path):
            app.logger.info(f"Graph file exists: {graph_path}")
        else:
            app.logger.error(f"Graph file does not exist: {graph_path}")
            return render_template('error.html', message="Failed to generate graph."), 500

        # Generate the URL for the graph image
        graph_url = url_for('static', filename=f'graphs/{username}_graph.png')
        app.logger.info(f"Graph URL: {graph_url}")

        # Move the graph file to the static directory
        static_graph_dir = os.path.join(app.static_folder, 'graphs')
        os.makedirs(static_graph_dir, exist_ok=True)
        static_graph_path = os.path.join(static_graph_dir, f"{username}_graph.png")
        shutil.move(graph_path, static_graph_path)
        return render_template('graph.html', username=username, graph_url=graph_url)

    except Exception as e:
        app.logger.error(f"Error: {str(e)}")
        return render_template('error.html', message=f"An error occurred: {str(e)}"), 500
    finally:
        conn.close()
@app.route('/user-pie/<username>')
def user_pie(username):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT material, SUM(footprint) FROM carbon_footprint WHERE username=? GROUP BY material", (username,))
        data = cursor.fetchall()

        if not data:
            return render_template('error.html', message="No data available for this user."), 404

        # Extract labels (materials) and values (footprint sum)
        labels = [row[0] for row in data]
        values = [row[1] for row in data]

        if not values:
            return render_template('error.html', message="No footprint data available for pie chart."), 400

        # Ensure the static/graphs directory exists
        graph_dir = "static/graphs/"
        if not os.path.exists(graph_dir):
            os.makedirs(graph_dir)

        # Save Pie Chart
        pie_chart_path = os.path.join(graph_dir, f"{username}_pie.png")
        colors = plt.cm.Paired(np.linspace(0, 1, len(labels)))
        plt.figure(figsize=(6, 6))
        plt.pie(values, labels=labels, autopct='%1.1f%%', colors=colors)
        plt.title(f"{username}'s Carbon Footprint Breakdown")
        plt.savefig(pie_chart_path)
        plt.close()

        # Pass the image URL to the HTML template
        return render_template('pie_chart.html', username=username, pie_chart_url=f"/{pie_chart_path}")

    except Exception as e:
        app.logger.error(f"Error: {str(e)}")
        return f"Error: {str(e)}", 500
    finally:
        conn.close()
@app.route('/user-badge', methods=['GET'])
def user_badge():
    if 'user' not in session:
        return jsonify({"error": "User not logged in"}), 401

    username = session['user']
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT users.username, SUM(carbon_footprint.footprint) as total_footprint, users.credit_points
            FROM users
            LEFT JOIN carbon_footprint ON users.username = carbon_footprint.username
            WHERE users.username = ?
            GROUP BY users.username
        """, (username,))
        user = cursor.fetchone()

        if not user:
            return jsonify({"error": "No data available for this user"}), 404

        cursor.execute("""
            SELECT COUNT(*) + 1 AS rank
            FROM (
                SELECT users.username
                FROM users
                LEFT JOIN carbon_footprint ON users.username = carbon_footprint.username
                GROUP BY users.username
                HAVING SUM(carbon_footprint.footprint) < ?
            )
        """, (user['total_footprint'],))
        rank = cursor.fetchone()['rank']

        # Assign title based on rank
        if rank == 1:
            title = "🏆 Eco Warrior"
        elif rank <= 3:
            title = "🥈 Green Advocate"
        elif rank <= 10:
            title = "🥉 Sustainability Champion"
        else:
            title = "🌍 Participant"

        return jsonify({
            "username": user['username'],
            "total_footprint": user['total_footprint'] or 0,
            "credit_points": user['credit_points'] or 0,
            "rank": rank,
            "title": title
        })

    except Exception as e:
        app.logger.error(f"Error fetching user badge: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        conn.close()        
@app.route('/leaderboard')
def leaderboard():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT users.username, SUM(carbon_footprint.footprint) as total_footprint, users.credit_points
            FROM users
            LEFT JOIN carbon_footprint ON users.username = carbon_footprint.username
            GROUP BY users.username
            ORDER BY users.credit_points DESC, total_footprint ASC        """)
        users = cursor.fetchall()

        # Assign titles based on rank
        total_users = len(users)
        leaderboard_data = []
        for i, user in enumerate(users):
            username = user['username']
            total_footprint = user['total_footprint'] or 0
            credit_points = user['credit_points'] or 0

            # Assign titles based on rank
            if i < total_users * 0.1:  # Top 10%
                title = "🏆 Eco Warrior"
            elif i < total_users * 0.3:  # Next 20%
                title = "🥈 Green Advocate"
            elif i < total_users * 0.5:  # Next 30%
                title = "🥉 Sustainability Champion"
            else:
                title = "🌍 Participant"

            leaderboard_data.append({
                "username": username,
                "total_footprint": total_footprint,
                "credit_points": credit_points,
                "title": title
            })

        return render_template('leaderboard.html', leaderboard_data=leaderboard_data)

    except Exception as e:
        app.logger.error(f"Error: {str(e)}")
        return f"Error: {str(e)}", 500
    finally:
        conn.close()
@app.route('/weekly-graph')
def weekly_graph():
    user = session.get('user')
    if not user:
        return jsonify({'error': 'User not logged in'}), 401

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT strftime('%W', date) AS week, SUM(footprint) as total_emission
            FROM carbon_footprint
            WHERE username=?
            GROUP BY week
            ORDER BY week;
        """, (user,))
        data = cursor.fetchall()

        if not data:
            return render_template('error.html', message="No data available for this user."), 404

        weeks = [int(row['week']) for row in data]  # Convert to int for sorting
        emissions = [row['total_emission'] for row in data]

        cursor.execute("""
            SELECT date, footprint FROM carbon_footprint
            WHERE username=? ORDER BY footprint ASC LIMIT 1;
        """, (user,))
        best_day_row = cursor.fetchone()
        best_day = best_day_row['date'] if best_day_row else "N/A"
        best_day_emission = best_day_row['footprint'] if best_day_row else 0

        cursor.execute("""
            SELECT date, footprint FROM carbon_footprint
            WHERE username=? ORDER BY footprint DESC LIMIT 1;
        """, (user,))
        worst_day_row = cursor.fetchone()
        worst_day = worst_day_row['date'] if worst_day_row else "N/A"
        worst_day_emission = worst_day_row['footprint'] if worst_day_row else 0

    # Calculate emission change
        last_week_emission = emissions[-2] if len(emissions) > 1 else 0
        comparison = "↓ Reduced" if emissions[-1] < last_week_emission else "↑ Increased"
    
    # Calculate streak
        reduced_emission = emissions[-1] < last_week_emission
        streak = 1 if reduced_emission else 0
        
        weeks_numeric = np.arange(len(weeks))
        emissions_smooth = np.interp(weeks_numeric, weeks_numeric, emissions)

        plt.figure(figsize=(9, 5), facecolor='#F5F5F5')  # Light gray background
        plt.plot(weeks_numeric, emissions_smooth, marker='o', linestyle='-', color='#4A90E2', linewidth=2.5, alpha=0.9, label="Carbon Footprint")

        # Add gradient fill under the line
        plt.fill_between(weeks_numeric, emissions_smooth, color='#4A90E2', alpha=0.3)

        # Aesthetics
        plt.xticks(weeks_numeric, [f"Week {w}" for w in weeks], rotation=30, fontsize=10)
        plt.yticks(fontsize=10)
        plt.xlabel("Week", fontsize=12, fontweight='bold', color='#555')
        plt.ylabel("Total Carbon Footprint", fontsize=12, fontweight='bold', color='#555')
        plt.title(f"{user}'s Weekly Carbon Footprint", fontsize=14, fontweight='bold', color='#333')
        plt.grid(axis='y', linestyle='--', alpha=0.5)  # Light gridlines

        # Save the graph
        graph_path = f"static/graphs/{user}_weekly.png"
        plt.savefig(graph_path, dpi=100, bbox_inches='tight')
        plt.close()
        print("Total Emission:", emissions[-1])
        print("Last Week Emission:", last_week_emission)
        print("Comparison:", comparison)
        print("Best Day:", best_day, best_day_emission)
        print("Worst Day:", worst_day, worst_day_emission)
        print("Streak:", streak)

        return render_template('weekly_graph.html', 
                           username=user, 
                           graph_url=url_for('static', filename=f'graphs/{user}_weekly.png'),
                           total_emission=emissions[-1],
                           last_week_emission=last_week_emission,
                           comparison=comparison,
                           best_day=best_day,
                           best_day_emission=best_day_emission,
                           worst_day=worst_day,
                           worst_day_emission=worst_day_emission,
                           streak=streak,
                           reduced_emission=reduced_emission)
    except Exception as e:
        app.logger.error(f"Error: {str(e)}")
        return f"Error: {str(e)}", 500
    finally:
        conn.close()


@app.route('/materials-info')
def materials_info():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, material, description, material_footprint, biodegradability, recyclability, eco_rating FROM materials")
    materials = cursor.fetchall()
    conn.close()

    materials_list = [dict(row) for row in materials]
    return render_template('materials_info.html', materials=materials_list)
# Helper function to determine badge class based on eco_rating
def get_eco_badge_class(rating):
    if rating == 'Eco-Friendly':
        return 'bg-success'
    elif rating == 'Moderate':
        return 'bg-warning text-dark'
    elif rating == 'High Impact':
        return 'bg-danger'
    return 'bg-secondary'

# Register the helper function in Jinja2

app.jinja_env.globals.update(get_eco_badge_class=get_eco_badge_class)


@app.route('/admin/view-analytics')
def view_analytics():
    if 'admin' not in session:
        return redirect(url_for('admin_login_page'))

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Get basic stats
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM carbon_footprint")
        record_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(footprint) FROM carbon_footprint")
        total_footprint = cursor.fetchone()[0] or 0
        
        # Get material distribution
        cursor.execute("""
            SELECT m.material, COUNT(cf.id) as count, SUM(cf.footprint) as total 
            FROM materials m
            LEFT JOIN carbon_footprint cf ON m.material = cf.material
            GROUP BY m.material
            ORDER BY total DESC
        """)
        material_data = cursor.fetchall()
        
        # Get weekly trends
        cursor.execute("""
            SELECT strftime('%W', date) as week, SUM(footprint) as total
            FROM carbon_footprint
            GROUP BY week
            ORDER BY week
            LIMIT 8
        """)
        weekly_data = cursor.fetchall()
        
        # Get top users
        cursor.execute("""
            SELECT username, SUM(footprint) as total
            FROM carbon_footprint
            GROUP BY username
            ORDER BY total DESC
            LIMIT 5
        """)
        top_users = cursor.fetchall()
        
        return render_template('view_analytics.html',
                           user_count=user_count,
                           record_count=record_count,
                           total_footprint=total_footprint,
                           material_data=material_data,
                           weekly_data=weekly_data,
                           top_users=top_users)
        
    except Exception as e:
        app.logger.error(f"Error fetching analytics: {str(e)}")
        return render_template('view_analytics.html', error=str(e))
    finally:
        conn.close()

if __name__ == '__main__':
    app.run(debug=True)

