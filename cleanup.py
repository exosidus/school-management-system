#!/usr/bin/env python3
"""
Cleanup script to remove unnecessary files and fix database
"""
import os
import sqlite3

def cleanup_project():
    # Remove unnecessary files
    files_to_remove = [
        'pending_approval.html'  # Not used
    ]
    
    for file in files_to_remove:
        file_path = f'templates/{file}'
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"Removed: {file_path}")
    
    # Fix database if exists
    if os.path.exists('elemis.db'):
        conn = sqlite3.connect('elemis.db')
        conn.row_factory = sqlite3.Row
        
        try:
            # Check if new schema exists
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            table_names = [table['name'] for table in tables]
            
            if 'roles' not in table_names:
                print("Database needs schema update. Please run: python init_admin.py")
            else:
                print("Database schema is up to date")
                
        except Exception as e:
            print(f"Database check error: {e}")
        finally:
            conn.close()
    
    print("Cleanup completed!")

if __name__ == '__main__':
    cleanup_project()