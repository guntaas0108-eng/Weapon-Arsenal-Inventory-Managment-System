"""
WAIMS — Weapon Arsenal Inventory Management System
Run:  python run.py
Open: http://localhost:8000
"""
import sys, os, uvicorn
sys.path.insert(0, os.path.dirname(__file__))

if __name__ == "__main__":
    print("=" * 52)
    print("  WAIMS — Inventory Management System")
    print("  http://localhost:8000")
    print("  admin / admin123   |   officer / officer123")
    print("=" * 52)
    uvicorn.run("backend.main:app", host="127.0.0.1",
                port=8000, reload=True)
