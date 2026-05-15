#!/usr/bin/env python3
"""
Database backup utility for e-School
"""

import sqlite3
import os
import shutil
from datetime import datetime
import gzip

def backup_database(db_path='elemis.db', backup_dir='backups'):
    """Create a backup of the database"""
    
    # Create backup directory if it doesn't exist
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
    
    # Generate backup filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f'elemis_backup_{timestamp}.db'
    backup_path = os.path.join(backup_dir, backup_filename)
    
    try:
        # Copy database file
        shutil.copy2(db_path, backup_path)
        
        # Compress backup
        compressed_path = backup_path + '.gz'
        with open(backup_path, 'rb') as f_in:
            with gzip.open(compressed_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Remove uncompressed backup
        os.remove(backup_path)
        
        print(f"✅ Database backup created: {compressed_path}")
        return compressed_path
        
    except Exception as e:
        print(f"❌ Backup failed: {e}")
        return None

def restore_database(backup_path, db_path='elemis.db'):
    """Restore database from backup"""
    
    try:
        # Check if backup file exists
        if not os.path.exists(backup_path):
            print(f"❌ Backup file not found: {backup_path}")
            return False
        
        # Create backup of current database
        if os.path.exists(db_path):
            current_backup = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy2(db_path, current_backup)
            print(f"📋 Current database backed up to: {current_backup}")
        
        # Decompress and restore
        if backup_path.endswith('.gz'):
            with gzip.open(backup_path, 'rb') as f_in:
                with open(db_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
        else:
            shutil.copy2(backup_path, db_path)
        
        print(f"✅ Database restored from: {backup_path}")
        return True
        
    except Exception as e:
        print(f"❌ Restore failed: {e}")
        return False

def cleanup_old_backups(backup_dir='backups', retention_days=30):
    """Remove backups older than retention_days"""
    
    if not os.path.exists(backup_dir):
        return
    
    cutoff_time = datetime.now().timestamp() - (retention_days * 24 * 60 * 60)
    removed_count = 0
    
    for filename in os.listdir(backup_dir):
        if filename.startswith('elemis_backup_'):
            file_path = os.path.join(backup_dir, filename)
            if os.path.getmtime(file_path) < cutoff_time:
                os.remove(file_path)
                removed_count += 1
    
    if removed_count > 0:
        print(f"🗑️ Removed {removed_count} old backup(s)")

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == 'backup':
            backup_database()
            cleanup_old_backups()
        elif sys.argv[1] == 'restore' and len(sys.argv) > 2:
            restore_database(sys.argv[2])
        else:
            print("Usage:")
            print("  python backup.py backup")
            print("  python backup.py restore <backup_file>")
    else:
        backup_database()
        cleanup_old_backups()