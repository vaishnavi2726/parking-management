import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import sqlite3
from datetime import datetime
import qrcode
import os

# Optional image display for QR popup
try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

# Optional: ANPR dependencies (not strictly required)
try:
    import cv2
    import pytesseract
except ImportError:
    cv2 = None
    pytesseract = None


DB_NAME = "parking.db"
TOTAL_SLOTS = 12
PRICE_PER_HOUR = 20  # base price per hour


# ---------- DATABASE LAYER ----------

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    # Admins
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL
        )
    """)

    # End users (non-admin)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL
        )
    """)

    # Bookings
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            slot_no INTEGER PRIMARY KEY,
            owner_name TEXT NOT NULL,
            vehicle_no TEXT NOT NULL,
            checkin_time TEXT NOT NULL,
            qr_path TEXT,
            created_by TEXT
        )
    """)

    # Payments
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_no INTEGER NOT NULL,
            amount REAL NOT NULL,
            hours_charged INTEGER NOT NULL,
            method TEXT NOT NULL,
            txn_id TEXT,
            paid_at TEXT NOT NULL
        )
    """)

    # Default accounts
    cur.execute("INSERT OR IGNORE INTO admins (username, password) VALUES (?, ?)", ("admin", "admin123"))
    cur.execute("INSERT OR IGNORE INTO users (username, password) VALUES (?, ?)", ("user", "user123"))

    conn.commit()
    conn.close()


def db_query(query, params=(), fetch=False):
    """Small helper to execute queries."""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(query, params)
    data = cur.fetchall() if fetch else None
    conn.commit()
    conn.close()
    return data


# ---------- ANPR (AUTO NUMBER PLATE RECOGNITION) ----------

def recognize_plate(image_path: str) -> str:
    """
    Tries to read number plate text from image using OpenCV + Tesseract.
    If dependencies are missing or fails, returns demo value "TEST1234".
    """
    if cv2 is None or pytesseract is None:
        return "TEST1234"  # demo / fallback

    try:
        img = cv2.imread(image_path)
        if img is None:
            return "TEST1234"
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        text = pytesseract.image_to_string(gray)
        text = "".join(ch for ch in text if ch.isalnum()).upper()
        if len(text) < 4:
            return "TEST1234"
        return text[:10]
    except Exception:
        return "TEST1234"


# ---------- MAIN APP CLASS ----------

class ParkingSystemApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Smart Parking Management System")
        self.root.geometry("900x550")
        self.root.minsize(850, 500)

        init_db()
        self._setup_style()

        self.current_user = None
        self.current_role = None  # "admin" or "user"

        self.main_frame = ttk.Frame(self.root, padding=20)
        self.main_frame.pack(fill="both", expand=True)

        self._build_login_screen()

    # ----- STYLE / THEME -----

    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        bg = "#1e1e1e"
        fg = "#ffffff"
        accent = "#3b82f6"
        danger = "#ef4444"

        self.root.configure(bg=bg)
        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=fg, font=("Segoe UI", 11))
        style.configure("TButton", font=("Segoe UI", 10, "bold"), padding=6)
        style.map(
            "TButton",
            background=[("active", accent), ("!active", "#2563eb")],
            foreground=[("disabled", "#9ca3af"), ("!disabled", "#ffffff")]
        )
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), foreground="#facc15")
        style.configure("Card.TFrame", background="#111827", relief="ridge", borderwidth=1)
        style.configure("Grid.TButton", font=("Segoe UI", 9, "bold"))

        self.slot_colors = {
            "free": "#16a34a",   # green
            "booked": danger,    # red
        }

    def _clear_main(self):
        for w in self.main_frame.winfo_children():
            w.destroy()

    # ---------- LOGIN / REGISTER SCREENS ----------

    def _build_login_screen(self):
        self._clear_main()
        card = ttk.Frame(self.main_frame, style="Card.TFrame", padding=30)
        card.place(relx=0.5, rely=0.5, anchor="center")

        ttk.Label(card, text="Parking System Login", style="Title.TLabel").grid(row=0, column=0, columnspan=2, pady=(0, 20))

        ttk.Label(card, text="Role:").grid(row=1, column=0, sticky="e", pady=5, padx=5)
        self.role_var = tk.StringVar(value="admin")
        role_combo = ttk.Combobox(card, textvariable=self.role_var, values=["admin", "user"], state="readonly")
        role_combo.grid(row=1, column=1, pady=5, padx=5)

        ttk.Label(card, text="Username:").grid(row=2, column=0, sticky="e", pady=5, padx=5)
        self.username_entry = ttk.Entry(card, width=25)
        self.username_entry.grid(row=2, column=1, pady=5, padx=5)

        ttk.Label(card, text="Password:").grid(row=3, column=0, sticky="e", pady=5, padx=5)
        self.password_entry = ttk.Entry(card, show="*", width=25)
        self.password_entry.grid(row=3, column=1, pady=5, padx=5)

        login_btn = ttk.Button(card, text="Login", command=self._handle_login)
        login_btn.grid(row=4, column=0, columnspan=2, pady=(15, 5), sticky="ew")

        sep = ttk.Separator(card)
        sep.grid(row=5, column=0, columnspan=2, pady=10, sticky="ew")

        ttk.Label(card, text="New user? (User role only)").grid(row=6, column=0, columnspan=2)
        register_btn = ttk.Button(card, text="Register as User", command=self._handle_register)
        register_btn.grid(row=7, column=0, columnspan=2, pady=(5, 0), sticky="ew")

    def _handle_login(self):
        role = self.role_var.get()
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()

        if not username or not password:
            messagebox.showwarning("Missing", "Please enter username and password.")
            return

        if role == "admin":
            rows = db_query("SELECT * FROM admins WHERE username=? AND password=?", (username, password), fetch=True)
        else:
            rows = db_query("SELECT * FROM users WHERE username=? AND password=?", (username, password), fetch=True)

        if rows:
            self.current_user = username
            self.current_role = role
            self._build_dashboard()
        else:
            messagebox.showerror("Login failed", "Invalid credentials.")

    def _handle_register(self):
        username = simpledialog.askstring("Register User", "Choose a username:")
        if not username:
            return
        password = simpledialog.askstring("Register User", "Choose a password:", show="*")
        if not password:
            return
        try:
            db_query("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
            messagebox.showinfo("Success", "User registered. Login as 'user'.")
        except sqlite3.IntegrityError:
            messagebox.showerror("Error", "Username already exists.")

    # ---------- DASHBOARD ----------

    def _build_dashboard(self):
        self._clear_main()

        header = ttk.Frame(self.main_frame)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text=f"Dashboard ({self.current_role.upper()})", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text=f"Logged in as: {self.current_user}").pack(side="left", padx=20)
        ttk.Button(header, text="Logout", command=self._logout).pack(side="right")

        body = ttk.Frame(self.main_frame)
        body.pack(fill="both", expand=True)

        # Left control panel
        left = ttk.Frame(body)
        left.pack(side="left", fill="y", padx=(0, 15))

        ttk.Button(left, text="Book Slot", width=20, command=self._book_slot_dialog).pack(pady=5)
        ttk.Button(left, text="Checkout & Pay", width=20, command=self._checkout_dialog).pack(pady=5)
        ttk.Button(left, text="View Slot Grid (Window)", width=20, command=self._open_slot_grid).pack(pady=5)
        ttk.Button(left, text="Show Summary", width=20, command=self._show_summary).pack(pady=5)

        if self.current_role == "admin":
            ttk.Button(left, text="View Payments", width=20, command=self._view_payments).pack(pady=5)

        # Embedded slot grid on dashboard
        self.grid_frame = ttk.Frame(body, style="Card.TFrame", padding=10)
        self.grid_frame.pack(side="left", fill="both", expand=True)
        ttk.Label(self.grid_frame, text="Live Slot View", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        self.slots_container = ttk.Frame(self.grid_frame)
        self.slots_container.pack(fill="both", expand=True, pady=(10, 0))
        self._build_slots_grid(self.slots_container)

    def _logout(self):
        self.current_user = None
        self.current_role = None
        self._build_login_screen()

    # ---------- SLOT GRID ----------

    def _get_booked_slots(self):
        rows = db_query("SELECT slot_no FROM bookings", fetch=True)
        return {r[0] for r in rows}

    def _build_slots_grid(self, parent):
        for w in parent.winfo_children():
            w.destroy()
        booked = self._get_booked_slots()

        rows = 3
        cols = TOTAL_SLOTS // rows + (1 if TOTAL_SLOTS % rows else 0)
        slot = 1
        for r in range(rows):
            for c in range(cols):
                if slot > TOTAL_SLOTS:
                    break
                state = "booked" if slot in booked else "free"
                text = f"{slot}"
                btn = tk.Button(
                    parent,
                    text=text,
                    width=8,
                    height=2,
                    relief="raised",
                    bd=1,
                    bg=self.slot_colors[state],
                    fg="white",
                    font=("Segoe UI", 9, "bold"),
                    command=lambda s=slot, st=state: self._slot_clicked(s, st),
                )
                btn.grid(row=r, column=c, padx=5, pady=5, sticky="nsew")
                parent.grid_rowconfigure(r, weight=1)
                parent.grid_columnconfigure(c, weight=1)
                slot += 1

    def _refresh_grid(self):
        self._build_slots_grid(self.slots_container)

    def _slot_clicked(self, slot_no, state):
        if state == "free":
            if messagebox.askyesno("Book Slot", f"Slot {slot_no} is free. Book it?"):
                self._book_slot_dialog(prefilled_slot=slot_no)
        else:
            info = db_query(
                "SELECT owner_name, vehicle_no, checkin_time FROM bookings WHERE slot_no=?",
                (slot_no,),
                fetch=True,
            )
            if info:
                owner, vehicle, checkin = info[0]
                messagebox.showinfo(
                    f"Slot {slot_no} (Booked)",
                    f"Owner: {owner}\nVehicle: {vehicle}\nCheck-in: {checkin}",
                )

    # ---------- BOOKING FLOW (WITH ANPR & QR POPUP) ----------

    def _book_slot_dialog(self, prefilled_slot=None):
        dlg = tk.Toplevel(self.root)
        dlg.title("Book Parking Slot")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.configure(bg="#111827")
        frm = ttk.Frame(dlg, padding=20)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Book Slot", style="Title.TLabel").grid(row=0, column=0, columnspan=3, pady=(0, 15))

        ttk.Label(frm, text="Owner Name:").grid(row=1, column=0, sticky="e", pady=5, padx=5)
        owner_entry = ttk.Entry(frm, width=30)
        owner_entry.grid(row=1, column=1, columnspan=2, pady=5, padx=5)

        ttk.Label(frm, text="Vehicle No:").grid(row=2, column=0, sticky="e", pady=5, padx=5)
        vehicle_entry = ttk.Entry(frm, width=30)
        vehicle_entry.grid(row=2, column=1, pady=5, padx=5)

        # ANPR button
        def do_anpr():
            path = filedialog.askopenfilename(
                title="Select Vehicle Image",
                filetypes=[("Image files", "*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff"), ("All files", "*.*")]
            )
            if not path:
                return
            plate = recognize_plate(path)
            vehicle_entry.delete(0, tk.END)
            vehicle_entry.insert(0, plate)
            messagebox.showinfo("ANPR Result", f"Detected Plate: {plate}")

        anpr_btn = ttk.Button(frm, text="Read from Image (ANPR)", command=do_anpr)
        anpr_btn.grid(row=2, column=2, padx=5)

        ttk.Label(frm, text="Preferred Slot (optional):").grid(row=3, column=0, sticky="e", pady=5, padx=5)
        slot_var = tk.StringVar(value=str(prefilled_slot) if prefilled_slot else "")
        slot_entry = ttk.Entry(frm, width=10, textvariable=slot_var)
        slot_entry.grid(row=3, column=1, sticky="w", pady=5, padx=5)

        def submit():
            owner = owner_entry.get().strip()
            vehicle = vehicle_entry.get().strip().upper()
            slot_pref = slot_var.get().strip()

            if not owner or not vehicle:
                messagebox.showwarning("Missing", "Owner and Vehicle are required.")
                return

            booked = self._get_booked_slots()
            slot_no = None

            if slot_pref:
                try:
                    s = int(slot_pref)
                    if not (1 <= s <= TOTAL_SLOTS):
                        raise ValueError
                    if s in booked:
                        messagebox.showerror("Slot taken", f"Slot {s} is already booked.")
                        return
                    slot_no = s
                except ValueError:
                    messagebox.showerror("Invalid", "Preferred slot must be a number within range.")
                    return

            if slot_no is None:
                for s in range(1, TOTAL_SLOTS + 1):
                    if s not in booked:
                        slot_no = s
                        break

            if slot_no is None:
                messagebox.showerror("Full", "No free slots available.")
                return

            self._book_slot(slot_no, owner, vehicle)
            dlg.destroy()
            self._refresh_grid()

        btn_row = ttk.Frame(frm)
        btn_row.grid(row=4, column=0, columnspan=3, pady=(15, 0))
        ttk.Button(btn_row, text="Cancel", command=dlg.destroy).pack(side="right", padx=5)
        ttk.Button(btn_row, text="Book", command=submit).pack(side="right", padx=5)

    def _book_slot(self, slot_no, owner, vehicle):
        checkin = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        qr_text = f"Slot: {slot_no}\nOwner: {owner}\nVehicle: {vehicle}\nCheck-In: {checkin}"
        os.makedirs("tickets", exist_ok=True)
        qr_path = os.path.join("tickets", f"ticket_slot_{slot_no}.png")
        img = qrcode.make(qr_text)
        img.save(qr_path)

        db_query(
            "INSERT OR REPLACE INTO bookings (slot_no, owner_name, vehicle_no, checkin_time, qr_path, created_by) VALUES (?, ?, ?, ?, ?, ?)",
            (slot_no, owner, vehicle, checkin, qr_path, self.current_user or "system"),
        )

        self._show_qr_popup(qr_path, slot_no)

    def _show_qr_popup(self, qr_path, slot_no):
        popup = tk.Toplevel(self.root)
        popup.title(f"Ticket for Slot {slot_no}")
        popup.transient(self.root)
        popup.grab_set()
        popup.configure(bg="#111827")
        frm = ttk.Frame(popup, padding=15)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text=f"QR Ticket - Slot {slot_no}", style="Title.TLabel").pack(pady=(0, 10))

        if Image and ImageTk and os.path.exists(qr_path):
            img = Image.open(qr_path)
            img = img.resize((200, 200))
            photo = ImageTk.PhotoImage(img)
            lbl = ttk.Label(frm)
            lbl.image = photo
            lbl.configure(image=photo)
            lbl.pack(pady=5)
        else:
            ttk.Label(frm, text=f"QR saved at:\n{qr_path}").pack(pady=10)

        ttk.Button(frm, text="Close", command=popup.destroy).pack(pady=(10, 0))

    # ---------- CHECKOUT + PAYMENT ----------

    def _checkout_dialog(self):
        slot_no = simpledialog.askinteger("Checkout", "Enter Slot Number to checkout:")
        if not slot_no:
            return
        row = db_query(
            "SELECT owner_name, vehicle_no, checkin_time FROM bookings WHERE slot_no=?",
            (slot_no,),
            fetch=True,
        )
        if not row:
            messagebox.showwarning("Not found", "Slot is not currently booked.")
            return

        owner, vehicle, checkin = row[0]
        checkin_dt = datetime.strptime(checkin, "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        hours = max(1, int((now - checkin_dt).total_seconds() / 3600))
        amount = hours * PRICE_PER_HOUR

        if not messagebox.askyesno(
            "Confirm Checkout",
            f"Slot: {slot_no}\nOwner: {owner}\nVehicle: {vehicle}\n"
            f"Hours: {hours}\nAmount: ₹{amount}\n\nProceed to payment?",
        ):
            return

        self._payment_dialog(slot_no, amount, hours)

    def _payment_dialog(self, slot_no, amount, hours):
        # NOTE: This is a simulated payment UI. Real integration (UPI/Razorpay/Stripe)
        # would require API keys and HTTP requests.
        dlg = tk.Toplevel(self.root)
        dlg.title("Payment")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.configure(bg="#111827")
        frm = ttk.Frame(dlg, padding=20)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Payment", style="Title.TLabel").grid(row=0, column=0, columnspan=2, pady=(0, 10))
        ttk.Label(frm, text=f"Slot: {slot_no}").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Label(frm, text=f"Amount: ₹{amount}").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Label(frm, text=f"Hours: {hours}").grid(row=3, column=0, sticky="w", pady=3)

        ttk.Label(frm, text="Method:").grid(row=4, column=0, sticky="w", pady=(10, 3))
        method_var = tk.StringVar(value="UPI")
        methods = ["UPI", "Card", "Cash"]
        method_combo = ttk.Combobox(frm, textvariable=method_var, values=methods, state="readonly", width=10)
        method_combo.grid(row=4, column=1, sticky="w", pady=(10, 3))

        ttk.Label(frm, text="Transaction ID (optional):").grid(row=5, column=0, sticky="w", pady=3)
        txn_entry = ttk.Entry(frm, width=20)
        txn_entry.grid(row=5, column=1, sticky="w", pady=3)

        def complete_payment():
            method = method_var.get()
            txn_id = txn_entry.get().strip() or None
            paid_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            db_query(
                "INSERT INTO payments (slot_no, amount, hours_charged, method, txn_id, paid_at) VALUES (?, ?, ?, ?, ?, ?)",
                (slot_no, amount, hours, method, txn_id, paid_at),
            )
            db_query("DELETE FROM bookings WHERE slot_no=?", (slot_no,))
            dlg.destroy()
            self._refresh_grid()
            messagebox.showinfo("Payment successful", "Checkout and payment completed.")

        btn_row = ttk.Frame(frm)
        btn_row.grid(row=6, column=0, columnspan=2, pady=(15, 0))
        ttk.Button(btn_row, text="Cancel", command=dlg.destroy).pack(side="right", padx=5)
        ttk.Button(btn_row, text="Pay", command=complete_payment).pack(side="right", padx=5)

    # ---------- OTHER VIEWS ----------

    def _open_slot_grid(self):
        win = tk.Toplevel(self.root)
        win.title("Slot Grid")
        win.geometry("500x300")
        win.configure(bg="#111827")
        frm = ttk.Frame(win, padding=10)
        frm.pack(fill="both", expand=True)
        self._build_slots_grid(frm)

    def _show_summary(self):
        total = TOTAL_SLOTS
        booked = len(self._get_booked_slots())
        free = total - booked
        paid_rows = db_query("SELECT SUM(amount) FROM payments", fetch=True)
        total_revenue = paid_rows[0][0] if paid_rows and paid_rows[0][0] is not None else 0
        messagebox.showinfo(
            "Summary",
            f"Total slots: {total}\nBooked: {booked}\nFree: {free}\n\nTotal revenue: ₹{total_revenue:.2f}",
        )

    def _view_payments(self):
        rows = db_query("SELECT slot_no, amount, method, paid_at FROM payments ORDER BY paid_at DESC", fetch=True)
        if not rows:
            messagebox.showinfo("Payments", "No payments recorded yet.")
            return
        lines = []
        for slot_no, amount, method, paid_at in rows:
            lines.append(f"Slot {slot_no} | ₹{amount} | {method} | {paid_at}")
        messagebox.showinfo("Payments", "\n".join(lines))


# ---------- RUN APP ----------

if __name__ == "__main__":
    root = tk.Tk()
    app = ParkingSystemApp(root)
    root.mainloop()