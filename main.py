from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
from typing import List, Optional

app = FastAPI(title="City Somsa POS API", version="3.1")

# CORS sozlamasi (Frontend va Backend erkin bog'lanishi uchun)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_NAME = "city_somsa.db"

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# Ma'lumotlar bazasini yaratish
def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Foydalanuvchilar jadvali
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        phone TEXT PRIMARY KEY,
        pass_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        name TEXT NOT NULL
    )""")
    
    # Somsa turlari va narxlari
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS somsa_types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price INTEGER NOT NULL
    )""")
    
    # Ishlab chiqarish (Somsachi)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS production_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        worker TEXT NOT NULL,
        status TEXT NOT NULL,
        somsa_id INTEGER,
        somsa_name TEXT NOT NULL,
        qty INTEGER NOT NULL,
        price INTEGER NOT NULL,
        worker_fee INTEGER NOT NULL
    )""")
    
    # Sotuvlar (Kassa)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sales_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        seller TEXT NOT NULL,
        customer TEXT NOT NULL,
        payment_type TEXT NOT NULL,
        total INTEGER NOT NULL
    )""")
    
    # Sotuv ichidagi mahsulotlar
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sale_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER,
        somsa_id INTEGER,
        name TEXT NOT NULL,
        price INTEGER NOT NULL,
        qty INTEGER NOT NULL,
        FOREIGN KEY(sale_id) REFERENCES sales_logs(id)
    )""")
    
    # Audit va so'rovlar
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        action TEXT NOT NULL,
        target_id INTEGER,
        phone TEXT,
        new_pass_hash TEXT,
        new_qty INTEGER,
        requested_by TEXT NOT NULL,
        reason TEXT NOT NULL,
        status TEXT NOT NULL
    )""")
    
    # Boshlang'ich somsa turlarini kiritish (agar bo'sh bo'lsa)
    cursor.execute("SELECT COUNT(*) FROM somsa_types")
    if cursor.fetchone()[0] == 0:
        default_somsa = [
            ("Mol go'shtli", 10000),
            ("Qo'y go'shtli", 12000),
            ("Avashnoy", 6000),
            ("Qiyma", 8000),
            ("Kartoshkali", 5000),
            ("Qovoqli", 5000),
            ("Tovuqli", 8000)
        ]
        cursor.executemany("INSERT INTO somsa_types (name, price) VALUES (?, ?)", default_somsa)
        
    conn.commit()
    conn.close()

init_db()

# --- MODELLAR (Pydantic) ---
class UserRegister(BaseModel):
    phone: str
    pass_hash: str
    role: str
    name: str

class ProductionCreate(BaseModel):
    date: str
    time: str
    worker: str
    status: str
    somsa_id: int
    somsa_name: str
    qty: int
    price: int
    worker_fee: int

class SaleItemModel(BaseModel):
    id: int
    name: str
    price: int
    qty: int

class SaleCreate(BaseModel):
    date: str
    time: str
    seller: str
    customer: str
    payment_type: str
    total: int
    items: List[SaleItemModel]

# --- API ENDPOINTLAR ---

@app.get("/api/users")
def get_users():
    conn = get_db()
    users = conn.execute("SELECT phone, role, name FROM users").fetchall()
    conn.close()
    return [dict(u) for u in users]

@app.post("/api/users")
def create_user(user: UserRegister):
    conn = get_db()
    try:
        conn.execute("INSERT INTO users (phone, pass_hash, role, name) VALUES (?, ?, ?, ?)",
                     (user.phone, user.pass_hash, user.role, user.name))
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Bu telefon raqam allaqachon mavjud!")
    finally:
        conn.close()
    return {"status": "success"}

@app.get("/api/somsa-types")
def get_somsa_types():
    conn = get_db()
    types = conn.execute("SELECT * FROM somsa_types").fetchall()
    conn.close()
    return [dict(t) for t in types]

@app.post("/api/production")
def add_production(prod: ProductionCreate):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO production_logs (date, time, worker, status, somsa_id, somsa_name, qty, price, worker_fee)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (prod.date, prod.time, prod.worker, prod.status, prod.somsa_id, prod.somsa_name, prod.qty, prod.price, prod.worker_fee))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.get("/api/production")
def get_production(date: Optional[str] = None):
    conn = get_db()
    if date:
        logs = conn.execute("SELECT * FROM production_logs WHERE date = ? ORDER BY id DESC", (date,)).fetchall()
    else:
        logs = conn.execute("SELECT * FROM production_logs ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(l) for l in logs]

@app.post("/api/sales")
def create_sale(sale: SaleCreate):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO sales_logs (date, time, seller, customer, payment_type, total)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (sale.date, sale.time, sale.seller, sale.customer, sale.payment_type, sale.total))
    sale_id = cursor.lastrowid
    
    for item in sale.items:
        cursor.execute("""
            INSERT INTO sale_items (sale_id, somsa_id, name, price, qty)
            VALUES (?, ?, ?, ?, ?)
        """, (sale_id, item.id, item.name, item.price, item.qty))
        
    conn.commit()
    conn.close()
    return {"status": "success", "sale_id": sale_id}

@app.get("/api/sales")
def get_sales(date: Optional[str] = None):
    conn = get_db()
    if date:
        sales = conn.execute("SELECT * FROM sales_logs WHERE date = ? ORDER BY id DESC", (date,)).fetchall()
    else:
        sales = conn.execute("SELECT * FROM sales_logs ORDER BY id DESC").fetchall()
    
    result = []
    for s in sales:
        s_dict = dict(s)
        items = conn.execute("SELECT somsa_id as id, name, price, qty FROM sale_items WHERE sale_id = ?", (s['id'],)).fetchall()
        s_dict['items'] = [dict(i) for i in items]
        result.append(s_dict)
        
    conn.close()
    return result
