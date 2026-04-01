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
import shutil
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import base64
import io
from PIL import Image

load_dotenv()

app = Flask(__name__)
app.secret_key = "your_secret_key"  # Required for session management

# Ensure the static/graphs directory exists
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GRAPH_DIR = os.path.join(BASE_DIR, "static/graphs")
os.makedirs(GRAPH_DIR, exist_ok=True)

# Fabric keywords to CO2 mapping (blended fabric support)
FABRIC_CO2 = {
    'cotton':             5.90,
    'polyester':          9.52,
    'nylon':              7.20,
    'wool':              10.00,
    'linen':              1.90,
    'viscose':            4.50,
    'rayon':              4.50,
    'elastane':          28.00,
    'spandex':           28.00,
    'acrylic':            7.60,
    'silk':               6.00,
    'hemp':               2.10,
    'lyocell':            2.40,
    'tencel':             2.40,
    'recycled polyester': 3.50,
    'organic cotton':     3.80,
}

def parse_fabric_blend(text):
    """
    Extract fabric percentages from OCR text.
    Handles formats like: '60% Cotton 40% Polyester'
    """
    text = text.lower()
    results = []

    # Match patterns like "60% cotton" or "cotton 60%"
    pattern = r'(\d+)\s*%\s*([a-z\s]+?)(?=\d+\s*%|$|,|\n)'
    matches = re.findall(pattern, text)

    for percent_str, fabric_name in matches:
        fabric_name = fabric_name.strip().rstrip(',').strip()
        percent = int(percent_str) / 100.0

        for known_fabric in FABRIC_CO2:
            if known_fabric in fabric_name or fabric_name in known_fabric:
                results.append({
                    'fabric': known_fabric,
                    'percent': percent,
                    'co2_per_kg': FABRIC_CO2[known_fabric]
                })
                break

    return results

def calculate_blended_co2(blend_list, weight_kg):
    total_co2 = 0
    for item in blend_list:
        total_co2 += item['co2_per_kg'] * item['percent'] * weight_kg
    return round(total_co2, 3)

# Additional Sustainability Metrics
FABRIC_WATER_LITERS_PER_KG = {
    'cotton (conventional)': 10000,
    'organic cotton': 2500,
    'polyester': 60,
    'recycled polyester': 50,
    'nylon': 100,
    'wool': 5000,
    'linen/flax': 2000,
    'viscose/rayon': 1000
}

FABRIC_MICROPLASTICS_GRAMS_PER_KG = {
    'polyester': 1.5,
    'recycled polyester': 1.5,
    'nylon': 1.2,
    # Natural fibers shed biodegradable material, not persistent microplastics
    'cotton (conventional)': 0.0,
    'organic cotton': 0.0,
    'wool': 0.0,
    'linen/flax': 0.0,
    'viscose/rayon': 0.0
}

BRAND_MULTIPLIERS = {
    'Generic / Unknown': 1.0,
    'Shein': 1.5,        # Ultra fast fashion penalty
    'Zara': 1.3,         # Fast fashion penalty
    'H&M': 1.3,
    'Levis': 1.1,        # Better, but resource intensive
    'Patagonia': 0.7,    # Eco-conscious discount
    'Pact': 0.7,
    'Tentree': 0.6       # Very high carbon offset operations
}

# Helper for Carbon Interface API
def get_shipping_emission(weight, distance_km=1000):
    api_key = os.environ.get('CARBON_INTERFACE_API_KEY')
    if not api_key or api_key == 'YOUR_CARBON_INTERFACE_KEY':
        return None
        
    try:
        response = requests.post(
            "https://beta.carboninterface.com/api/v1/estimates",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "type": "shipping",
                "weight_value": weight if weight > 0 else 1,
                "weight_unit": "kg",
                "distance_value": distance_km,
                "distance_unit": "km",
                "transport_method": "truck"
            },
            timeout=5
        )
        if response.status_code == 201 or response.status_code == 200:
            return response.json()["data"]["attributes"]["carbon_kg"]
        else:
            app.logger.warning(f"Carbon API Error: {response.text}")
    except Exception as e:
        app.logger.error(f"Carbon API Request Failed: {str(e)}")
    return None

# Function to connect to SQLite
def get_db_connection():
    db_path = 'carbon_footprint_db.db'
    
    # Vercel fix: Filesystem is read-only except for /tmp
    if os.environ.get('VERCEL'):
        tmp_db_path = os.path.join('/tmp', 'carbon_footprint_db.db')
        if not os.path.exists(tmp_db_path):
            # Seed the /tmp database from the included one
            if os.path.exists(db_path):
                import shutil
                shutil.copy(db_path, tmp_db_path)
            else:
                # If the original doesn't exist (unlikely), just create path
                db_path = tmp_db_path
        db_path = tmp_db_path

    conn = sqlite3.connect(db_path)
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
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Calculate community impact: assume average non-eco item footprint is 15kg.
        # Savings = 15 - actual footprint
        cursor.execute("SELECT SUM(15.0 - footprint) FROM carbon_footprint WHERE footprint < 15.0")
        saved_co2 = cursor.fetchone()[0] or 0.0
        saved_co2 = round(saved_co2, 1)
        return render_template('home.html', saved_co2=saved_co2)
    except Exception as e:
        app.logger.error(f"Error fetching saved CO2: {str(e)}")
        return render_template('home.html', saved_co2=0.0)
    finally:
        conn.close()

@app.route('/impact')
def impact():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT AVG(footprint) FROM carbon_footprint")
        avg_footprint = cursor.fetchone()[0] or 12.0
        
        # Scenario: if 40M college students reduced their garment footprint by 10%
        # assuming the user logs roughly 50 garments a year (avg)
        annual_footprint_per_student = avg_footprint * 50
        potential_savings = annual_footprint_per_student * 0.10 * 40000000
        
        return render_template('impact.html', potential_savings=potential_savings)
    except Exception as e:
        return f"Error: {e}", 500
    finally:
        conn.close()

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
    
    # Auto-seed the database if materials are missing (e.g. user has not run update_db.py)
    if len(materials) < 5:
        # Default scientifically baked emission factors
        defaults = [
            ('Cotton (conventional)', 5.9, 'Moderate'),
            ('Polyester', 9.52, 'High Impact'),
            ('Nylon', 7.2, 'High Impact'),
            ('Wool', 10.0, 'Moderate'),
            ('Viscose/Rayon', 4.5, 'Moderate'),
            ('Linen/Flax', 1.9, 'Eco-Friendly'),
            ('Organic cotton', 3.8, 'Eco-Friendly'),
            ('Recycled polyester', 3.5, 'Eco-Friendly')
        ]
        
        for mat in defaults:
            try:
                cursor.execute("INSERT INTO materials (material, material_footprint, eco_rating) VALUES (?, ?, ?)", mat)
            except Exception as e:
                pass # skip if already exists or fails
        conn.commit()
        
        # Re-fetch the populated list
        cursor.execute("SELECT material FROM materials")
        materials = cursor.fetchall()

    conn.close()

    brands = list(BRAND_MULTIPLIERS.keys())
    return render_template('calculator.html', materials=materials, brands=brands)

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

    data = request.get_json(silent=True) or request.form
    app.logger.debug(f"Incoming data: {data}")  # Log the incoming data

    # Validate required fields
    if not data.get('material') or not data.get('drying_method') or not data.get('washing_frequency') or not data.get('is_wearing_today'):
        app.logger.error("Missing required fields")
        return jsonify({"error": "Missing required fields: material, drying_method, washing_frequency, or is_wearing_today"}), 400

    material = data.get('material')
    drying_method = data.get('drying_method')
    washing_frequency = data.get('washing_frequency')
    ironing_frequency = data.get('ironing_frequency', 'Rarely')
    country_of_origin = data.get('country_of_origin', 'Local')
    brand = data.get('brand', 'Generic / Unknown')
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
            carbon_footprint *= weight * 0.1  # Example: weight factor

        # Shipping addition based on Country of Origin using Live APIs
        country_distances = {
            "Local": 100,
            "Asia": 8000,
            "Europe": 3000,
            "Americas": 5000
        }
        distance_km = country_distances.get(country_of_origin, 100)
        shipping_emission = get_shipping_emission(weight=max(weight, 1.0), distance_km=distance_km)
        
        if shipping_emission is not None:
            carbon_footprint += shipping_emission
        else:
            carbon_footprint += distance_km * 0.00015

        # Apply Brand Penalty/Discount Multiplier
        b_multiplier = BRAND_MULTIPLIERS.get(brand, 1.0)
        carbon_footprint *= b_multiplier

        carbon_footprint = round(carbon_footprint, 2)

        # Calculate Resale Index (Circular Economy Feature)
        resale_multipliers = {
            'linen': 0.6, 'wool': 0.55, 'silk': 0.5, 'cotton': 0.45, 
            'organic cotton': 0.52, 'nylon': 0.25, 'polyester': 0.15, 'viscose': 0.3
        }
        material_mult = resale_multipliers.get(mat_key, 0.2)
        
        # Brand impact on resale
        brand_resale_mult = 1.0
        if b_multiplier < 0.8: # Eco brand
            brand_resale_mult = 1.35
        elif b_multiplier > 1.2: # Fast fashion
            brand_resale_mult = 0.45
            
        # Estimated Resale Value ($40 base price * quality factors)
        resale_value = 40 * material_mult * brand_resale_mult

        # Save the record if the user is wearing the material today
        if is_wearing_today == 1:
            cursor.execute("""
                INSERT INTO carbon_footprint (username, date, material, washing_frequency, drying_method, ironing_frequency, weight, footprint, is_wearing_today)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (session['user'], get_ist_time(), material, washing_frequency, drying_method, ironing_frequency, weight, carbon_footprint, is_wearing_today))
            conn.commit()

        return jsonify({
            "message": "Calculation Successful",
            "carbon_footprint": f"{carbon_footprint:.2f} kg of CO2",
            "water_liters": water_liters,
            "microplastics_grams": micro_grams,
            "brand_multiplier": b_multiplier,
            "resale_value": round(resale_value, 2)
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
        return redirect(url_for('home'))  # Redirect to home if not logged in

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get user data
    cursor.execute("SELECT * FROM users WHERE username = ?", (user,))
    user_info = cursor.fetchone()

    # Default monthly budget logic
    budget_kg = 15.0  # Default budget limit
    
    # Calculate current month's emissions
    current_month = datetime.now().strftime('%Y-%m')
    cursor.execute("SELECT SUM(footprint) FROM carbon_footprint WHERE username = ? AND date LIKE ?", (user, f"{current_month}%"))
    monthly_emissions_raw = cursor.fetchone()[0]
    monthly_emissions = round(monthly_emissions_raw, 2) if monthly_emissions_raw else 0.0
    
    # Calculate Total Wardrobe Resale Value (Approximation)
    resale_multipliers = {
        'linen': 0.6, 'wool': 0.55, 'silk': 0.5, 'cotton': 0.45, 
        'organic cotton': 0.52, 'nylon': 0.25, 'polyester': 0.15, 'viscose': 0.3
    }
    total_resale = 0
    cursor.execute("SELECT material FROM carbon_footprint WHERE username = ?", (user,))
    all_items = cursor.fetchall()
    for item in all_items:
        mat = item[0].lower()
        mult = resale_multipliers.get(mat, 0.2)
        total_resale += 40 * mult
    
    total_resale = round(total_resale, 2)


    # Fetch user's carbon footprint entries
    cursor.execute("SELECT date, material, footprint FROM carbon_footprint WHERE username = ? ORDER BY date DESC", (user,))
    data = cursor.fetchall()
    conn.close()

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Execute query using the session user
        cursor.execute("SELECT COALESCE(SUM(footprint), 0), COALESCE(AVG(footprint), 0) FROM carbon_footprint WHERE username=?", (user,))
        result = cursor.fetchone()
        total, avg = result if result else (0, 0)
        
        # Scikit-learn trend prediction
        predicted_december = 0.0
        forecast_msg = ""
        forecast_val = 0.0
        try:
            cursor.execute("SELECT date, footprint FROM carbon_footprint WHERE username=? AND is_wearing_today=1 ORDER BY date", (user,))
            records = cursor.fetchall()
            
            if len(records) > 2:
                from sklearn.linear_model import LinearRegression
                import numpy as np
                
                # Prepare cumulative footprint over time
                X = []
                y = []
                cumulative = 0
                start_date = datetime.strptime(records[0]['date'][:10], '%Y-%m-%d')
                
                for r in records:
                    current_date = datetime.strptime(r['date'][:10], '%Y-%m-%d')
                    days_since_start = (current_date - start_date).days
                    cumulative += r['footprint']
                    X.append([days_since_start])
                    y.append(cumulative)
                
                model = LinearRegression().fit(X, y)
                
                # Predict for Dec 31 of current year
                target_date = datetime(start_date.year, 12, 31)
                days_to_target = (target_date - start_date).days
                prediction = model.predict([[max(days_to_target, X[-1][0] + 30)]])[0]
                forecast_val = round(prediction, 1)
                predicted_december = max(total, forecast_val)
                forecast_msg = "Projected annual footprint"
        except Exception as e:
            app.logger.error(f"Prediction Error: {e}")

        return render_template(
            'user-data.html', 
            user=user_info,
            username=user,
            data=data, 
            enumerate=enumerate, 
            total_emission=total,
            avg_emission=avg,
            forecast_message=forecast_msg, 
            forecast_val=forecast_val,
            predicted_december=predicted_december,
            monthly_emissions=monthly_emissions,
            budget_kg=budget_kg,
            total_resale=total_resale
        )
    
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
        static_graph_dir = os.path.join(app.static_folder, 'graphs')
        os.makedirs(static_graph_dir, exist_ok=True)

        # Save the graph directly to the static directory
        graph_filename = f"{username}_graph.png"
        static_graph_path = os.path.join(static_graph_dir, graph_filename)
        plt.savefig(static_graph_path)
        plt.close()
        
        app.logger.info(f"Graph saved at: {static_graph_path}")

        # Generate the URL for the graph image
        graph_url = url_for('static', filename=f'graphs/{graph_filename}')
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
@app.route('/api/user-pie-data')
def api_user_pie_data():
    user = session.get('user')
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
        
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT material, SUM(footprint) FROM carbon_footprint WHERE username=? GROUP BY material", (user,))
        data = cursor.fetchall()
        
        labels = [row[0] for row in data]
        values = [row[1] for row in data]
        return jsonify({"labels": labels, "values": values}), 200
    except Exception as e:
        app.logger.error(f"Error fetching pie data: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        conn.close()

@app.route('/user-badge')
def user_badge():
    if 'user' not in session:
        return jsonify({"badge": "🌍", "title": "Guest"}), 401

    username = session['user']
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Get user's own stats
        cursor.execute("SELECT COUNT(*), AVG(footprint) FROM carbon_footprint WHERE username=?", (username,))
        row = cursor.fetchone()
        count = row[0]
        avg = row[1] or 0.0

        # Global ranking logic
        cursor.execute("""
            SELECT username, SUM(footprint) as total_footprint
            FROM carbon_footprint
            GROUP BY username
            ORDER BY total_footprint ASC
        """)
        all_users = cursor.fetchall()
        
        user_rank = 1
        found = False
        for i, u in enumerate(all_users):
            if u['username'] == username:
                user_rank = i + 1
                found = True
                break
        
        if not found:
             # Basic title based on count/avg if no records
             if count == 0:
                 return jsonify({"badge": "🌱", "title": "Seedling", "rank": "N/A"})
        
        # Determine Title and Emoji Badge
        if user_rank == 1 and count > 0:
            badge, title = "🏆", "Eco Warrior"
        elif avg > 0 and avg < 3.0:
            badge, title = "🛡️", "Planet Guardian"
        elif avg > 0 and avg < 5.0:
            badge, title = "🌿", "Carbon Neutralist"
        elif count > 5:
            badge, title = "⚔️", "Eco-Warrior"
        else:
            badge, title = "🌍", "Green Citizen"

        return jsonify({
            "username": username,
            "badge": badge,
            "title": title,
            "rank": user_rank,
            "avg_footprint": round(avg, 2)
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


@app.route('/api/user-pie-data')
def user_pie_data():
    user = session.get('user')
    if not user:
        return jsonify({"labels": [], "values": []})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT material, SUM(footprint) as total 
        FROM carbon_footprint 
        WHERE username = ? 
        GROUP BY material
    """, (user,))
    rows = cursor.fetchall()
    conn.close()
    
    labels = [row[0] for row in rows]
    values = [round(row[1], 2) for row in rows]
    
    return jsonify({"labels": labels, "values": values})



@app.route('/api/scrape-product', methods=['GET'])
def scrape_product():
    url = request.args.get('url')
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        text = soup.get_text().lower()
        
        # Heuristic for Material Scraper
        # Look for percentages followed by material names
        found_materials = []
        materials_in_db = ["cotton", "polyester", "nylon", "wool", "viscose", "linen", "silk", "acrylic"]
        
        # Regex to find "80% Cotton" or "Cotton 80%"
        for material in materials_in_db:
            pattern = rf'(\d+)%\s*{material}|{material}\s*(\d+)%'
            match = re.search(pattern, text)
            if match:
                percentage = match.group(1) or match.group(2)
                found_materials.append({"material": material.capitalize(), "percentage": int(percentage)})
        
        # If no percentages found, just look for the first material mentioned
        if not found_materials:
            for material in materials_in_db:
                if material in text:
                    found_materials.append({"material": material.capitalize(), "percentage": 100})
                    break

        return jsonify({
            "success": True,
            "materials": found_materials,
            "url": url,
            "title": soup.title.string.strip() if soup.title else "Product Page"
        })

    except Exception as e:
        app.logger.error(f"Scraping Error: {str(e)}")
        return jsonify({"error": f"Failed to scrape URL: {str(e)}"}), 500

@app.route('/api/ai-advice')
def ai_advice():
    user = session.get('user')
    if not user:
        return jsonify({"advice": "Please log in to receive personalized sustainability coaching."})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(footprint), AVG(footprint), COUNT(*) FROM carbon_footprint WHERE username=?", (user,))
    row = cursor.fetchone()
    total = row[0] or 0
    avg = row[1] or 0
    count = row[2] or 0
    conn.close()

    if count == 0:
        advice = "Your journey starts here! Try calculating your first item to see where you stand."
    elif total > 50:
        advice = f"Your total footprint is {total:.1f}kg. This is equivalent to driving a car for 200 miles! Consider switching your most frequent material (Nylon/Polyester) to Organic Cotton to cut emissions by 40%."
    elif avg > 7:
        advice = "Your average item impact is high. This is common with fast-fashion brands. Try buying from certified B-Corp brands or secondhand markets to lower your average."
    elif avg < 3:
        advice = "Amazing! You are in the top 10% of sustainable shoppers. Your low-impact choices are setting a gold standard for the community."
    else:
        advice = "You're doing great! Small changes like air-drying your clothes instead of machine-drying can further reduce your footprint by up to 15%."

    return jsonify({
        "success": True,
        "advice": advice,
        "total": round(total, 2)
    })

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

