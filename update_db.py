import sqlite3

def main():
    conn = sqlite3.connect('carbon_footprint_db.db')
    cursor = conn.cursor()
    
    updates = {
        'Cotton (conventional)': 5.9,
        'Polyester': 9.52,
        'Nylon': 7.2,
        'Wool': 10.0,
        'Viscose/Rayon': 4.5,
        'Linen/Flax': 1.9,
        'Organic cotton': 3.8,
        'Recycled polyester': 3.5
    }
    
    for mat, fp in updates.items():
        cursor.execute("UPDATE materials SET material_footprint=? WHERE material=?", (fp, mat))
        cursor.execute("SELECT id FROM materials WHERE material=?", (mat,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO materials (material, description, material_footprint, eco_rating) VALUES (?, 'Updated Material', ?, 'Moderate')", (mat, fp))
            
    conn.commit()
    conn.close()
    print("Database updated successfully!")

if __name__ == "__main__":
    main()
