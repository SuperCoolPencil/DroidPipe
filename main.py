import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import os
import threading
import time
import re
import logging
import argparse

class ADBFileManager:
    def __init__(self, root):
        self.root = root
        self.root.title("DroidPipe - ADB File Manager")
        self.root.geometry("1000x700")
        
        # State
        self.local_cwd = os.path.expanduser("~")
        self.android_cwd = "/storage/emulated/0/"
        self.connected_device = None

        # Style
        self.style = ttk.Style()
        self.style.configure("Treeview", font=('Helvetica', 10), rowheight=25)
        self.style.configure("TButton", font=('Helvetica', 10, 'bold'))

        self._init_ui()
        self._check_connection()

    def _init_ui(self):
        # --- Top Bar (Status, Progress, Refresh) ---
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill=tk.X)
        
        # Status Label
        self.lbl_status = ttk.Label(top_frame, text="Checking ADB connection...", foreground="blue", width=40)
        self.lbl_status.pack(side=tk.LEFT)
        
        # Progress Bar (Hidden by default or stopped)
        self.progress_bar = ttk.Progressbar(top_frame, mode='indeterminate', length=200)
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        
        # Refresh Button
        btn_refresh = ttk.Button(top_frame, text="↻ Reconnect ADB", command=self._check_connection)
        btn_refresh.pack(side=tk.RIGHT)

        # --- Main Content (Dual Panes) ---
        paned_window = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned_window.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Left Frame (Local)
        left_frame = ttk.LabelFrame(paned_window, text="Local Machine (Linux)", padding=5)
        paned_window.add(left_frame, weight=1)
        
        self.lbl_local_path = ttk.Label(left_frame, text=self.local_cwd, relief="sunken", anchor="w")
        self.lbl_local_path.pack(fill=tk.X, pady=2)
        
        btn_frame_local = ttk.Frame(left_frame)
        btn_frame_local.pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame_local, text="🏠", command=self.go_home_local, width=3).pack(side=tk.LEFT)
        ttk.Button(btn_frame_local, text="⬆ Up (Esc)", command=self.go_up_local, width=10).pack(side=tk.LEFT)
        ttk.Button(btn_frame_local, text="⟳", command=self.refresh_local, width=3).pack(side=tk.LEFT)

        self.tree_local = self._create_treeview(left_frame)
        self.tree_local.bind("<Double-1>", self.on_local_interact)
        self.tree_local.bind("<Return>", self.on_local_interact)
        self.tree_local.bind("<Escape>", lambda e: self.go_up_local())
        
        # Navigation & Shortcuts (Local)
        self.tree_local.bind("<Right>", lambda e: self.tree_android.focus_set())
        self.tree_local.bind("<Shift-Right>", self.request_push_confirm)

        # Right Frame (Android)
        right_frame = ttk.LabelFrame(paned_window, text="Android Device", padding=5)
        paned_window.add(right_frame, weight=1)

        self.lbl_android_path = ttk.Label(right_frame, text=self.android_cwd, relief="sunken", anchor="w")
        self.lbl_android_path.pack(fill=tk.X, pady=2)
        
        btn_frame_android = ttk.Frame(right_frame)
        btn_frame_android.pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame_android, text="🏠", command=self.go_home_android, width=3).pack(side=tk.LEFT)
        ttk.Button(btn_frame_android, text="⬆ Up (Esc)", command=self.go_up_android, width=10).pack(side=tk.LEFT)
        ttk.Button(btn_frame_android, text="⟳", command=self.refresh_android, width=3).pack(side=tk.LEFT)

        self.tree_android = self._create_treeview(right_frame)
        self.tree_android.bind("<Double-1>", self.on_android_interact)
        self.tree_android.bind("<Return>", self.on_android_interact)
        self.tree_android.bind("<Escape>", lambda e: self.go_up_android())

        # Navigation & Shortcuts (Android)
        self.tree_android.bind("<Left>", lambda e: self.tree_local.focus_set())
        self.tree_android.bind("<Shift-Left>", self.request_pull_confirm)

        # --- Bottom Bar (Actions) ---
        action_frame = ttk.LabelFrame(self.root, text="Transfer Operations", padding=10)
        action_frame.pack(fill=tk.X, padx=10, pady=10)

        # Grid for centering
        action_frame.columnconfigure(0, weight=1)
        action_frame.columnconfigure(1, weight=1)
        action_frame.columnconfigure(2, weight=1)

        btn_push = ttk.Button(action_frame, text="Push to Android (Shift+Right) ➡", command=self.push_file)
        btn_push.grid(row=0, column=2, padx=10, sticky="ew")

        btn_pull = ttk.Button(action_frame, text="⬅ Pull to Local (Shift+Left)", command=self.pull_file)
        btn_pull.grid(row=0, column=0, padx=10, sticky="ew")
        
        ttk.Separator(action_frame, orient=tk.VERTICAL).grid(row=0, column=1, sticky="ns")

    def _create_treeview(self, parent):
        cols = ("Name", "Size", "Type")
        tree = ttk.Treeview(parent, columns=cols, show='headings', selectmode='browse')
        tree.heading("Name", text="Name")
        tree.heading("Size", text="Size")
        tree.heading("Type", text="Type")
        
        tree.column("Name", width=250)
        tree.column("Size", width=80, anchor="e")
        tree.column("Type", width=80, anchor="c")

        # Scrollbar
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        return tree

    # --- Utilities ---
    def select_first_item(self, tree):
        """Helper to select the first item in a treeview."""
        children = tree.get_children()
        if children:
            first = children[0]
            tree.selection_set(first)
            tree.focus(first)
            tree.see(first)

    def set_loading(self, is_loading):
        """Toggle indeterminate progress bar animation (e.g., for ls)."""
        if is_loading:
            self.progress_bar.config(mode='indeterminate')
            self.progress_bar.start(10) # Bounce every 10ms
        else:
            self.progress_bar.stop()
            self.progress_bar.config(mode='indeterminate')
            self.progress_bar['value'] = 0

    def set_progress(self, value):
        """Set determinate progress value (0-100)."""
        self.progress_bar.config(mode='determinate')
        self.progress_bar['value'] = value

    # --- ADB Logic ---
    def run_adb_cmd(self, cmd_list):
        """Runs a simple ADB command and returns (stdout, stderr)."""
        logging.debug(f"Running ADB command: {' '.join(cmd_list)}")
        try:
            full_cmd = ['adb'] + cmd_list
            result = subprocess.run(full_cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
            return result.stdout.strip(), result.stderr.strip()
        except FileNotFoundError:
            logging.error("ADB executable not found in PATH.")
            return None, "ADB executable not found in PATH."

    def run_adb_transfer(self, cmd_list, progress_callback):
        """Runs ADB command with -p and parses progress byte-by-byte for real-time updates."""
        logging.debug(f"Running ADB transfer command: {' '.join(cmd_list)}")
        try:
            full_cmd = ['adb'] + cmd_list
            
            # Use bufsize=0 (unbuffered) and binary mode to read bytes immediately.
            # This is critical because adb updates the same line using \r, 
            # and line-buffered text mode will wait for \n which never comes until the end.
            process = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0, 
            )
            
            output_buffer = b""
            while True:
                # Read 1 byte at a time to catch every update immediately
                char = process.stdout.read(1)
                if not char:
                    break
                
                output_buffer += char
                
                # Performance optimization: Only attempt to parse if we hit a % or ]
                # This prevents decoding the string on every single byte.
                if char in [b'%', b']']:
                    try:
                        # Decode only the recent part of the buffer
                        current_str = output_buffer[-100:].decode('utf-8', errors='ignore')
                        
                        # Regex to find percentage like [ 15%] or 15%
                        matches = list(re.finditer(r'(\d+)%', current_str))
                        if matches:
                            last_match = matches[-1]
                            p = int(last_match.group(1))
                            if progress_callback:
                                self.root.after(0, lambda val=p: progress_callback(val))
                    except Exception:
                        pass
            
            process.wait()
            return output_buffer.decode('utf-8', errors='replace'), process.returncode
        except FileNotFoundError:
            logging.error("ADB executable not found in PATH for transfer command.")
            return None, -1

    def _check_connection(self):
        def check():
            logging.info("Checking ADB connection...")
            self.root.after(0, lambda: self.set_loading(True))
            out, err = self.run_adb_cmd(['devices'])
            
            self.root.after(0, lambda: self.set_loading(False))

            if err and "not found" in err:
                logging.error("ADB executable not found.")
                self.update_status("Error: ADB not found.", "red")
                return

            if not out:
                self.connected_device = None
                logging.error("ADB Error: No output from \'adb devices\'.")
                self.update_status("ADB Error: No output.", "red")
                return

            lines = out.split('\n')[1:] # Skip header
            devices = [line for line in lines if line.strip() and 'device' in line]
            
            if devices:
                self.connected_device = devices[0].split()[0]
                logging.info(f"Connected to device: {self.connected_device}")
                self.update_status(f"Connected: {self.connected_device}", "green")
                self.root.after(0, self.refresh_android)
                self.root.after(0, self.refresh_local)
            else:
                self.connected_device = None
                logging.warning("No ADB devices found. Please connect a device and enable USB debugging.")
                self.update_status("No device found. Connect via USB & enable Debugging.", "red")
                # Clear android tree
                for item in self.tree_android.get_children():
                    self.tree_android.delete(item)

        threading.Thread(target=check, daemon=True).start()

    def update_status(self, msg, color="black"):
        self.lbl_status.config(text=msg, foreground=color)

    # --- Local File System Logic ---
    def refresh_local(self):
        logging.debug(f"Refreshing local directory: {self.local_cwd}")
        self.lbl_local_path.config(text=self.local_cwd)
        # Clear tree
        for item in self.tree_local.get_children():
            self.tree_local.delete(item)
        
        try:
            items = os.listdir(self.local_cwd)
            # Sort: Directories first, then files
            items.sort(key=lambda x: (not os.path.isdir(os.path.join(self.local_cwd, x)), x.lower()))

            for item in items:
                path = os.path.join(self.local_cwd, item)
                if os.path.isdir(path):
                    self.tree_local.insert('', 'end', values=(str(item), "", "Dir"), tags=('dir',))
                else:
                    size = f"{os.path.getsize(path) / 1024:.1f} KB"
                    self.tree_local.insert('', 'end', values=(str(item), size, "File"))
            
            self.select_first_item(self.tree_local)
            
        except PermissionError:
            logging.error(f"Permission denied for local directory: {self.local_cwd}")
            messagebox.showerror("Error", "Permission Denied")
            self.go_up_local()

    def go_up_local(self):
        logging.debug(f"Going up in local directory from: {self.local_cwd}")
        self.local_cwd = os.path.dirname(self.local_cwd)
        self.refresh_local()

    def go_home_local(self):
        logging.debug("Going to local home directory.")
        self.local_cwd = os.path.expanduser("~")
        self.refresh_local()

    def on_local_interact(self, event):
        sel = self.tree_local.selection()
        if not sel: 
            logging.debug("No item selected for local interaction.")
            return

        item_id = sel[0]
        item = self.tree_local.item(item_id)
        name = str(item['values'][0])
        itype = item['values'][2]

        logging.debug(f"Local item interacted: {name} (Type: {itype})")
        if itype == "Dir":
            self.local_cwd = os.path.join(self.local_cwd, name)
            self.refresh_local()

    # --- Android File System Logic ---
    def refresh_android(self):
        if not self.connected_device:
            logging.debug("Attempted to refresh Android, but no device is connected.")
            return

        def fetch():
            logging.debug(f"Refreshing Android directory: {self.android_cwd}")
            self.root.after(0, lambda: self.set_loading(True))
            cmd = ['shell', f'ls -p "{self.android_cwd}"']
            out, err = self.run_adb_cmd(cmd)
            self.root.after(0, lambda: self.set_loading(False))
            
            items_data = []
            if out:
                lines = out.splitlines()
                for line in lines:
                    line = line.strip()
                    if not line: continue
                    
                    if line.endswith('/'):
                        name = line[:-1]
                        items_data.append((name, "", "Dir"))
                    else:
                        items_data.append((line, "?", "File"))
            
            # Sort on UI thread
            self.root.after(0, lambda: self._update_android_tree(items_data))

        self.lbl_android_path.config(text=self.android_cwd)
        threading.Thread(target=fetch, daemon=True).start()

    def _update_android_tree(self, items):
        for item in self.tree_android.get_children():
            self.tree_android.delete(item)
        
        items.sort(key=lambda x: (x[2] != "Dir", x[0].lower()))

        for name, size, ftype in items:
            self.tree_android.insert('', 'end', values=(str(name), size, ftype))
        
        self.select_first_item(self.tree_android)

    def go_up_android(self):
        logging.debug(f"Going up in Android directory from: {self.android_cwd}")
        if self.android_cwd == "/":
            return
        
        new_path = os.path.dirname(self.android_cwd.rstrip('/'))
        if not new_path: 
            new_path = "/"
        if not new_path.endswith('/') and new_path != "/":
            new_path += "/"
        
        self.android_cwd = new_path
        self.refresh_android()

    def go_home_android(self):
        logging.debug("Going to Android home directory.")
        self.android_cwd = "/storage/emulated/0/"
        self.refresh_android()

    def on_android_interact(self, event):
        sel = self.tree_android.selection()
        if not sel: 
            logging.debug("No item selected for Android interaction.")
            return
        
        item_id = sel[0]
        item = self.tree_android.item(item_id)
        name = str(item['values'][0])
        itype = item['values'][2]

        logging.debug(f"Android item interacted: {name} (Type: {itype})")
        if itype == "Dir":
            if self.android_cwd == "/":
                self.android_cwd += name + "/"
            else:
                self.android_cwd = os.path.join(self.android_cwd, name) + "/"
            self.refresh_android()

    # --- Transfer Logic ---
    def request_push_confirm(self, event=None):
        """Shortcut wrapper for Push"""
        sel = self.tree_local.selection()
        if not sel: return
        
        name = str(self.tree_local.item(sel[0])['values'][0])
        logging.debug(f"Push confirmation requested for: {name}")
        if messagebox.askyesno("Confirm Push", f"Push '{name}' to Android?"):
            self.push_file()

    def request_pull_confirm(self, event=None):
        """Shortcut wrapper for Pull"""
        sel = self.tree_android.selection()
        if not sel: return

        name = str(self.tree_android.item(sel[0])['values'][0])
        logging.debug(f"Pull confirmation requested for: {name}")
        if messagebox.askyesno("Confirm Pull", f"Pull '{name}' to Computer?"):
            self.pull_file()

    def push_file(self):
        """ Local -> Android """
        sel = self.tree_local.selection()
        if not sel:
            logging.warning("Push initiated without a selected file.")
            messagebox.showinfo("Select File", "Please select a file on the Local side to push.")
            return
        
        item = self.tree_local.item(sel[0])
        name = str(item['values'][0])
        local_path = os.path.join(self.local_cwd, name)
        logging.info(f"Initiating push for local file: {local_path} to Android directory: {self.android_cwd}")
        
        def task():
            # Reset bar to 0 and determinate mode
            self.root.after(0, lambda: self.set_progress(0))
            
            start_t = time.time()
            self.update_status(f"Pushing {name}...", "orange")
            
            def update_ui_prog(val):
                self.set_progress(val)

            # Use -p for progress
            out, ret_code = self.run_adb_transfer(['push', '-p', local_path, self.android_cwd], update_ui_prog)
            
            duration = time.time() - start_t
            # Reset to empty state
            self.root.after(0, lambda: self.set_loading(False))

            if ret_code != 0:
                logging.error(f"Push failed for {name}: {out}")
                self.root.after(0, lambda: messagebox.showerror("Push Error", f"{out}"))
                self.root.after(0, lambda: self.update_status("Push Failed", "red"))
            else:
                logging.info(f"Push of {name} completed in {duration:.2f}s")
                self.root.after(0, self.refresh_android)
                self.root.after(0, lambda: self.update_status(f"Push Complete ({duration:.2f}s)", "green"))

        threading.Thread(target=task, daemon=True).start()

    def pull_file(self):
        """ Android -> Local """
        sel = self.tree_android.selection()
        if not sel:
            logging.warning("Pull initiated without a selected file.")
            messagebox.showinfo("Select File", "Please select a file on the Android side to pull.")
            return

        item = self.tree_android.item(sel[0])
        name = str(item['values'][0])
        android_path = os.path.join(self.android_cwd, name)
        logging.info(f"Initiating pull for Android file: {android_path} to local directory: {self.local_cwd}")
        if self.android_cwd.endswith('\\/'):
            android_path = self.android_cwd + name
        else:
            android_path = self.android_cwd + '/' + name

        def task():
            # Reset bar to 0 and determinate mode
            self.root.after(0, lambda: self.set_progress(0))
            
            start_t = time.time()
            self.update_status(f"Pulling {name}...", "orange")
            
            def update_ui_prog(val):
                self.set_progress(val)

            # Use -p for progress
            out, ret_code = self.run_adb_transfer(['pull', '-p', android_path, self.local_cwd], update_ui_prog)
            
            duration = time.time() - start_t
            self.root.after(0, lambda: self.set_loading(False))

            if ret_code != 0:
                logging.error(f"Pull failed for {name}: {out}")
                self.root.after(0, lambda: messagebox.showerror("Pull Error", f"{out}"))
                self.root.after(0, lambda: self.update_status("Pull Failed", "red"))
            else:
                logging.info(f"Pull of {name} completed in {duration:.2f}s")
                self.root.after(0, self.refresh_local)
                self.root.after(0, lambda: self.update_status(f"Pull Complete ({duration:.2f}s)", "green"))

        threading.Thread(target=task, daemon=True).start()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DroidPipe - ADB File Manager")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
        logging.debug("Debug logging enabled.")
    else:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        logging.info("Info logging enabled. Use -d or --debug for debug messages.")

    root = tk.Tk()
    app = ADBFileManager(root)
    root.mainloop()
