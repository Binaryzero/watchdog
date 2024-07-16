import os
import shutil
import time
import re
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

IGNORE_PATTERNS = [
    r'.*\.crdownload$',
    r'.*\.part$',
    r'.*\.temp$',
    r'.*\.tmp$',
    r'~\$.*\.(?:doc|docx|xls|xlsx)$',
    r'\..*\.swp$',
    r'.*\.DS_Store$'
]

def should_ignore(path):
    file_name = os.path.basename(path)
    return any(re.match(pattern, file_name) for pattern in IGNORE_PATTERNS)

def retry_on_error(func, *args, max_attempts=5, delay=1, **kwargs):
    for attempt in range(max_attempts):
        try:
            return func(*args, **kwargs)
        except (PermissionError, OSError) as e:
            if attempt == max_attempts - 1:
                logging.error(f"Failed to {func.__name__} after {max_attempts} attempts: {e}")
                return False
            logging.warning(f"Error in {func.__name__}, retrying in {delay} seconds: {e}")
            time.sleep(delay)
    return False

class BidirectionalSyncHandler(FileSystemEventHandler):
    def __init__(self, dir1, dir2):
        self.dir1 = dir1
        self.dir2 = dir2

    def on_any_event(self, event):
        if should_ignore(event.src_path):
            return

        # Determine which directory the event occurred in
        if event.src_path.startswith(self.dir1):
            src_dir, dest_dir = self.dir1, self.dir2
        else:
            src_dir, dest_dir = self.dir2, self.dir1

        src_path = event.src_path
        rel_path = os.path.relpath(src_path, src_dir)
        dest_path = os.path.join(dest_dir, rel_path)

        if event.event_type in ['created', 'modified']:
            if event.is_directory:
                retry_on_error(os.makedirs, dest_path, exist_ok=True)
                logging.info(f"Created directory: {dest_path}")
            else:
                retry_on_error(os.makedirs, os.path.dirname(dest_path), exist_ok=True)
                if retry_on_error(shutil.copy2, src_path, dest_path):
                    logging.info(f"Copied: {src_path} to {dest_path}")
        elif event.event_type == 'deleted':
            if os.path.exists(dest_path):
                if os.path.isdir(dest_path):
                    if retry_on_error(shutil.rmtree, dest_path):
                        logging.info(f"Deleted directory: {dest_path}")
                else:
                    if retry_on_error(os.remove, dest_path):
                        logging.info(f"Deleted file: {dest_path}")
        elif event.event_type == 'moved':
            if should_ignore(event.dest_path):
                return
            src_rel_path = os.path.relpath(event.src_path, src_dir)
            dest_rel_path = os.path.relpath(event.dest_path, src_dir)
            src_dest_path = os.path.join(dest_dir, src_rel_path)
            new_dest_path = os.path.join(dest_dir, dest_rel_path)
            
            if os.path.exists(src_dest_path):
                retry_on_error(os.makedirs, os.path.dirname(new_dest_path), exist_ok=True)
                if retry_on_error(shutil.move, src_dest_path, new_dest_path):
                    logging.info(f"Moved: {src_dest_path} to {new_dest_path}")

def sync_directories(dir1, dir2):
    # Initial sync from dir1 to dir2
    initial_sync(dir1, dir2)
    # Initial sync from dir2 to dir1
    initial_sync(dir2, dir1)
    
    handler = BidirectionalSyncHandler(dir1, dir2)
    observer1 = Observer()
    observer2 = Observer()
    observer1.schedule(handler, dir1, recursive=True)
    observer2.schedule(handler, dir2, recursive=True)
    observer1.start()
    observer2.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer1.stop()
        observer2.stop()
    observer1.join()
    observer2.join()

def initial_sync(source_dir, dest_dir):
    for root, dirs, files in os.walk(source_dir):
        rel_path = os.path.relpath(root, source_dir)
        dest_root = os.path.join(dest_dir, rel_path)
        
        retry_on_error(os.makedirs, dest_root, exist_ok=True)
        logging.info(f"Created directory: {dest_root}")

        for file in files:
            if should_ignore(file):
                continue
            source_file = os.path.join(root, file)
            dest_file = os.path.join(dest_root, file)
            
            if not os.path.exists(dest_file) or os.path.getmtime(source_file) > os.path.getmtime(dest_file):
                if retry_on_error(shutil.copy2, source_file, dest_file):
                    logging.info(f"Copied: {source_file} to {dest_file}")

    # Remove files/directories in dest that don't exist in source
    for root, dirs, files in os.walk(dest_dir, topdown=False):
        rel_path = os.path.relpath(root, dest_dir)
        source_root = os.path.join(source_dir, rel_path)
        
        for file in files:
            if should_ignore(file):
                continue
            dest_file = os.path.join(root, file)
            source_file = os.path.join(source_root, file)
            if not os.path.exists(source_file):
                if retry_on_error(os.remove, dest_file):
                    logging.info(f"Deleted file: {dest_file}")
        
        if not os.path.exists(source_root) and root != dest_dir:
            if retry_on_error(shutil.rmtree, root):
                logging.info(f"Deleted directory: {root}")

if __name__ == "__main__":
    dir1 = input("Enter the path for the first directory: ")
    dir2 = input("Enter the path for the second directory: ")

    if not os.path.exists(dir1) or not os.path.exists(dir2):
        print("One or both directories do not exist. Please create them and try again.")
    else:
        print(f"Syncing bidirectionally between {dir1} and {dir2}")
        print("Press Ctrl+C to stop the synchronization.")
        sync_directories(dir1, dir2)