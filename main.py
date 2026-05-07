from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
import mysql.connector, os, time

# ══════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════
SECRET    = "waims-thapar-ucs310-2025"
ALGO      = "HS256"
TOKEN_MIN = 60

# Local MySQL — your machine
DB = dict(
    host     = "localhost",
    database = "waims",
    user     = "root",
    password = "010806",
    port     = 3306,
    connection_timeout = 10
)

app = FastAPI(title="WAIMS API", version="3.0")
app.add_middleware(CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

crypt  = CryptContext(schemes=["sha256_crypt"], deprecated="auto")
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/login")

USERS = {
    "admin": {
        "username":"admin", "full_name":"System Administrator",
        "role":"Admin", "clearance":"TOP SECRET",
        "pw": crypt.hash("admin123")
    },
    "officer": {
        "username":"officer", "full_name":"Dr. Deepak Sharma",
        "role":"Officer", "clearance":"CONFIDENTIAL",
        "pw": crypt.hash("officer123")
    },
}

# ══════════════════════════════════════════════════
#  DB HELPERS
# ══════════════════════════════════════════════════
def get_conn():
    return mysql.connector.connect(**DB)

def fetch(sql, params=None):
    cn = get_conn()
    cu = cn.cursor(dictionary=True)
    cu.execute(sql, params or ())
    rows = cu.fetchall()
    cu.close(); cn.close()
    for r in rows:
        for k, v in r.items():
            if hasattr(v, "strftime"):
                r[k] = v.strftime("%Y-%m-%d")
            elif v is None:
                r[k] = None
    return rows

def run(sql, params=None):
    cn = get_conn()
    cu = cn.cursor()
    cu.execute(sql, params or ())
    cn.commit()
    lid = cu.lastrowid
    cu.close(); cn.close()
    return lid

def run_many(sql, rows):
    cn = get_conn()
    cu = cn.cursor()
    cu.executemany(sql, rows)
    cn.commit()
    cu.close(); cn.close()

def call_proc(name, args=()):
    cn = get_conn()
    cu = cn.cursor()
    cur_results = []
    cu.callproc(name, args)
    for r in cu.stored_results():
        cur_results.extend(r.fetchall())
    cn.commit()
    cu.close(); cn.close()
    return cur_results

# ══════════════════════════════════════════════════
#  DATABASE SETUP
# ══════════════════════════════════════════════════
def setup():
    cn = get_conn()
    cu = cn.cursor()

    # ── CREATE TABLES ─────────────────────────────
    cu.execute("""
        CREATE TABLE IF NOT EXISTS Category (
            category_id   INT AUTO_INCREMENT PRIMARY KEY,
            category_name VARCHAR(40)  NOT NULL,
            description   VARCHAR(200),
            class_level   VARCHAR(20)
        )
    """); cn.commit()

    cu.execute("""
        CREATE TABLE IF NOT EXISTS Weapon (
            weapon_id   INT AUTO_INCREMENT PRIMARY KEY,
            name        VARCHAR(50)  NOT NULL,
            category_id INT,
            serial_no   VARCHAR(30)  NOT NULL UNIQUE,
            quantity    INT          NOT NULL DEFAULT 1,
            condition_  VARCHAR(20)  NOT NULL DEFAULT 'Operational',
            location    VARCHAR(40),
            FOREIGN KEY (category_id) REFERENCES Category(category_id)
        )
    """); cn.commit()

    cu.execute("""
        CREATE TABLE IF NOT EXISTS Personnel (
            personnel_id INT AUTO_INCREMENT PRIMARY KEY,
            name         VARCHAR(80)  NOT NULL,
            rank_        VARCHAR(30),
            unit_        VARCHAR(50),
            clearance    VARCHAR(30),
            contact      VARCHAR(15)
        )
    """); cn.commit()

    cu.execute("""
        CREATE TABLE IF NOT EXISTS Issue (
            Issue_id     INT AUTO_INCREMENT PRIMARY KEY,
            weapon_id    INT NOT NULL,
            personnel_id INT NOT NULL,
            Issue_date   DATE,
            return_date  DATE,
            status_      VARCHAR(12)  NOT NULL DEFAULT 'IssueD',
            FOREIGN KEY (weapon_id)    REFERENCES Weapon(weapon_id),
            FOREIGN KEY (personnel_id) REFERENCES Personnel(personnel_id)
        )
    """); cn.commit()

    cu.execute("""
        CREATE TABLE IF NOT EXISTS Maintenance (
            Maintenance_id INT AUTO_INCREMENT PRIMARY KEY,
            weapon_id      INT NOT NULL,
            tech_id        VARCHAR(20),
            date_logged    DATE,
            type_          VARCHAR(40),
            outcome        VARCHAR(20) NOT NULL DEFAULT 'IN PROGRESS',
            next_due       DATE,
            FOREIGN KEY (weapon_id) REFERENCES Weapon(weapon_id)
        )
    """); cn.commit()

    cu.execute("""
        CREATE TABLE IF NOT EXISTS AuditLog (
            log_id      INT AUTO_INCREMENT PRIMARY KEY,
            action_     VARCHAR(20),
            tbl         VARCHAR(30),
            record_id   INT,
            description VARCHAR(255),
            logged_at   DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """); cn.commit()

   
    # ── DROP OLD TRIGGERS ─────────────────────────
    for t in ["trg_maint_check","trg_overdue",
              "trg_cond_change","trg_block_del"]:
        cu.execute(f"DROP TRIGGER IF EXISTS {t}")
        cn.commit()

    # ── TRIGGER 1: Auto-schedule Maintenance ──────
    cu.execute("""
        CREATE TRIGGER trg_maint_check
        AFTER INSERT ON Issue
        FOR EACH ROW
        BEGIN
            DECLARE v_last DATE;
            SELECT MAX(date_logged)
            INTO   v_last
            FROM   Maintenance
            WHERE  weapon_id = NEW.weapon_id;

            IF v_last IS NULL
               OR DATEDIFF(CURDATE(), v_last) > 180
            THEN
                INSERT INTO Maintenance
                    (weapon_id, tech_id, date_logged,
                     type_, outcome, next_due)
                VALUES
                    (NEW.weapon_id, 'AUTO-TRIGGER', CURDATE(),
                     'Scheduled Inspection', 'PENDING',
                     DATE_ADD(CURDATE(), INTERVAL 14 DAY));

                INSERT INTO AuditLog
                    (action_, tbl, record_id, description)
                VALUES
                    ('TRIGGER', 'Maintenance', NEW.weapon_id,
                     CONCAT('Auto-Maintenance for Weapon #',
                            NEW.weapon_id));
            END IF;
        END
    """); cn.commit()

    # ── TRIGGER 2: Flag overdue returns ───────────
    cu.execute("""
        CREATE TRIGGER trg_overdue
        BEFORE UPDATE ON Issue
        FOR EACH ROW
        BEGIN
            IF NEW.return_date IS NULL
               AND DATEDIFF(CURDATE(), OLD.Issue_date) > 30
               AND NEW.status_ != 'RETURNED'
            THEN
                SET NEW.status_ = 'OVERDUE';
            END IF;
        END
    """); cn.commit()

    # ── TRIGGER 3: Log condition changes ──────────
    cu.execute("""
        CREATE TRIGGER trg_cond_change
        AFTER UPDATE ON Weapon
        FOR EACH ROW
        BEGIN
            IF OLD.condition_ != NEW.condition_ THEN
                INSERT INTO AuditLog
                    (action_, tbl, record_id, description)
                VALUES
                    ('TRIGGER', 'Weapon', NEW.weapon_id,
                     CONCAT('Condition: ', OLD.condition_,
                            ' changed to ', NEW.condition_));
            END IF;
        END
    """); cn.commit()

    # ── TRIGGER 4: Block delete if Issued ─────────
    cu.execute("""
        CREATE TRIGGER trg_block_del
        BEFORE DELETE ON Weapon
        FOR EACH ROW
        BEGIN
            DECLARE v_cnt INT DEFAULT 0;
            SELECT COUNT(*) INTO v_cnt
            FROM   Issue
            WHERE  weapon_id = OLD.weapon_id
              AND  status_ IN ('IssueD','OVERDUE');

            IF v_cnt > 0 THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT =
                    'Cannot delete: Weapon is currently Issued';
            END IF;
        END
    """); cn.commit()

    # ── DROP OLD PROCEDURES ───────────────────────
    for p in ["sp_Issue","sp_return","sp_inventory"]:
        cu.execute(f"DROP PROCEDURE IF EXISTS {p}")
        cn.commit()

    # ── PROCEDURE 1: Issue Weapon ──────────────────
    cu.execute("""
        CREATE PROCEDURE sp_Issue(
            IN p_wid INT,
            IN p_pid INT
        )
        BEGIN
            DECLARE v_qty  INT     DEFAULT 0;
            DECLARE v_cond VARCHAR(20) DEFAULT '';

            SELECT quantity, condition_
            INTO   v_qty, v_cond
            FROM   Weapon
            WHERE  weapon_id = p_wid
            FOR UPDATE;

            IF v_qty < 1 OR v_cond != 'Operational' THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT =
                    'Weapon unavailable for Issue';
            END IF;

            INSERT INTO Issue
                (weapon_id, personnel_id, Issue_date, status_)
            VALUES
                (p_wid, p_pid, CURDATE(), 'IssueD');

            UPDATE Weapon
            SET    quantity = quantity - 1
            WHERE  weapon_id = p_wid;

            INSERT INTO AuditLog
                (action_, tbl, record_id, description)
            VALUES
                ('PROC', 'Issue', LAST_INSERT_ID(),
                 CONCAT('sp_Issue: Weapon #', p_wid,
                        ' Issued to Applicant #', p_pid));
        END
    """); cn.commit()

    # ── PROCEDURE 2: Return Weapon ─────────────────
    cu.execute("""
        CREATE PROCEDURE sp_return(IN p_iid INT)
        BEGIN
            DECLARE v_wid INT DEFAULT 0;

            SELECT weapon_id INTO v_wid
            FROM   Issue
            WHERE  Issue_id = p_iid;

            UPDATE Issue
            SET    return_date = CURDATE(),
                   status_     = 'RETURNED'
            WHERE  Issue_id = p_iid;

            UPDATE Weapon
            SET    quantity = quantity + 1
            WHERE  weapon_id = v_wid;

            INSERT INTO AuditLog
                (action_, tbl, record_id, description)
            VALUES
                ('PROC', 'Issue', p_iid,
                 CONCAT('sp_return: Weapon #', v_wid,
                        ' returned'));
        END
    """); cn.commit()

    # ── PROCEDURE 3: Inventory report ─────────────
    cu.execute("""
        CREATE PROCEDURE sp_inventory()
        BEGIN
            SELECT w.weapon_id, w.name,
                   c.category_name,
                   w.serial_no, w.quantity,
                   w.condition_, w.location
            FROM   Weapon w
            JOIN   Category c ON w.category_id = c.category_id
            ORDER  BY c.category_name, w.name;
        END
    """); cn.commit()

    # ── VIEWS ──────────────────────────────────────
    cu.execute("""
        CREATE OR REPLACE VIEW vw_active_issues AS
        SELECT i.Issue_id,
               w.name      AS Weapon,
               w.serial_no,
               p.name      AS applicant,
               p.rank_     AS student_id,
               p.unit_     AS department,
               p.clearance AS purpose,
               i.Issue_date,
               i.status_,
               DATEDIFF(CURDATE(), i.Issue_date) AS days_out
        FROM   Issue i
        JOIN   Weapon    w ON i.weapon_id    = w.weapon_id
        JOIN   Personnel p ON i.personnel_id = p.personnel_id
        WHERE  i.status_ IN ('IssueD','OVERDUE')
    """); cn.commit()

    cu.execute("""
        CREATE OR REPLACE VIEW vw_stock AS
        SELECT w.weapon_id, w.name,
               c.category_name,
               w.quantity, w.location
        FROM   Weapon w
        JOIN   Category c ON w.category_id = c.category_id
        WHERE  w.condition_ = 'Operational'
    """); cn.commit()

    cu.execute("""
        CREATE OR REPLACE VIEW vw_pending_maint AS
        SELECT w.name   AS Weapon,
               m.tech_id, m.type_,
               m.date_logged, m.next_due, m.outcome
        FROM   Maintenance m
        JOIN   Weapon w ON m.weapon_id = w.weapon_id
        WHERE  m.outcome != 'COMPLETED'
    """); cn.commit()

    # ── SEED DATA (only if empty) ──────────────────
    if True:  # Always seed after fresh table creation
        run_many(
            "INSERT INTO Category(category_name,description,class_level)"
            " VALUES(%s,%s,%s)", [
            ("Assault Rifle","Standard infantry rifles","CONFIDENTIAL"),
            ("Pistol",       "Sidearm handguns",        "RESTRICTED"),
            ("Sniper Rifle", "Long-range rifles",        "SECRET"),
            ("SMG",          "Submachine guns",          "CONFIDENTIAL"),
            ("LMG",          "Light machine guns",       "SECRET"),
        ])
        # run_many(
        #     "INSERT INTO Weapon(name,category_id,serial_no,"
        #     "quantity,condition_,location) VALUES(%s,%s,%s,%s,%s,%s)", [
        #     ("AK-47",         1,"AK-2021-001",45,"Operational",   "Bay A-1"),
        #     ("INSAS Rifle",   1,"IN-2019-022",30,"Operational",   "Bay A-2"),
        #     ("Glock 19",      2,"GL-2022-007",80,"Operational",   "Bay B-1"),
        #     ("SIG Sauer P320",2,"SG-2020-014",25,"Maintenance",   "Bay B-2"),
        #     ("L96 Sniper",    3,"L9-2018-003",10,"Operational",   "Bay C-1"),
        #     ("MP5",           4,"MP-2023-011",20,"Operational",   "Bay D-1"),
        #     ("M16A4",         1,"M1-2017-088", 0,"Decommissioned","Storage E-9"),
        # ])
        # run_many(
        #     "INSERT INTO Personnel(name,rank_,unit_,clearance,contact)"
        #     " VALUES(%s,%s,%s,%s,%s)", [
        #     ("Arjun Sharma","102417001","B.Tech CSE",  "NCC Training",  "9810001234"),
        #     ("Priya Nair",  "102417002","B.Tech ECE",  "Shooting Range","9820005678"),
        #     ("Rajan Verma", "102417003","B.Tech ME",   "Sports Event",  "9830009012"),
        #     ("Amit Yadav",  "102417004","B.Tech Civil","NCC Training",  "9840003456"),
        #     ("Sunita Devi", "102417005","B.Tech CSE",  "Security Duty", "9850007890"),
        # ])
        # run_many(
        #     "INSERT INTO Issue(weapon_id,personnel_id,"
        #     "Issue_date,return_date,status_) VALUES(%s,%s,%s,%s,%s)", [
        #     (1,1,"2025-03-01",None,        "IssueD"),
        #     (3,2,"2025-03-10","2025-03-25","RETURNED"),
        #     (5,3,"2025-04-01",None,        "IssueD"),
        #     (6,4,"2025-02-15","2025-02-28","RETURNED"),
        #     (2,1,"2025-01-10",None,        "OVERDUE"),
        # ])
        run_many(
            "INSERT INTO Maintenance(weapon_id,tech_id,date_logged,"
            "type_,outcome,next_due) VALUES(%s,%s,%s,%s,%s,%s)", [
            (4,"TECH-04","2025-04-01","Scheduled Inspection","IN PROGRESS","2025-10-01"),
            (1,"TECH-02","2025-02-15","Cleaning",            "COMPLETED",  "2025-08-15"),
            (7,"TECH-01","2025-01-20","Decommission Audit",  "COMPLETED",  None),
            (5,"TECH-03","2025-03-05","Scope Calibration",   "COMPLETED",  "2025-09-05"),
        ])
        print("  Sample data inserted")

    cu.close(); cn.close()
    print("  Tables OK | 4 Triggers OK | 3 Procedures OK | 3 Views OK")

# ══════════════════════════════════════════════════
#  AUTH
# ══════════════════════════════════════════════════
def make_token(sub):
    exp = datetime.utcnow() + timedelta(minutes=TOKEN_MIN)
    return jwt.encode({"sub":sub,"exp":exp}, SECRET, algorithm=ALGO)

async def auth(token: str = Depends(oauth2)):
    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALGO])
        u = USERS.get(payload.get("sub"))
        if not u: raise HTTPException(401,"Invalid token")
        return u
    except JWTError:
        raise HTTPException(401,"Token expired — please login again")

# ══════════════════════════════════════════════════
#  SCHEMAS
# ══════════════════════════════════════════════════
class WeaponIn(BaseModel):
    name:str; category:str; serial_no:str
    quantity:int; condition:str; location:str

class PersonnelIn(BaseModel):
    name:str; rank:str; unit:str; clearance:str; contact:str

class IssueIn(BaseModel):
    weapon_id:int; personnel_id:int

class MaintIn(BaseModel):
    weapon_id:int; tech_id:str; type:str

class QueryIn(BaseModel):
    query:str
    
   

class IssueWeaponRequest(BaseModel):

    weapon_id:int
    applicant_id:int
   

# ══════════════════════════════════════════════════
#  API ROUTES
# ══════════════════════════════════════════════════

@app.post("/api/login")
async def login(form: OAuth2PasswordRequestForm = Depends()):
    u = USERS.get(form.username)
    if not u or not crypt.verify(form.password, u["pw"]):
        raise HTTPException(401,"Invalid username or password")
    return {
        "access_token": make_token(form.username),
        "token_type":   "bearer",
        "user": {k:v for k,v in u.items() if k != "pw"}
    }

@app.get("/api/stats")
async def stats(u=Depends(auth)):
    w = fetch("SELECT IFNULL(SUM(quantity),0) tot,"
              " COUNT(*) types FROM Weapon")[0]
    return {
        "total_assets":    int(w["tot"]),
        "total_Weapons":   int(w["types"]),
        "operational":     fetch("SELECT COUNT(*) c FROM Weapon"
                                 " WHERE condition_='Operational'")[0]["c"],
        "Issued_now":      fetch("SELECT COUNT(*) c FROM Issue"
                                 " WHERE status_='IssueD'")[0]["c"],
        "overdue":         fetch("SELECT COUNT(*) c FROM Issue"
                                 " WHERE status_='OVERDUE'")[0]["c"],
        "in_Maintenance":  fetch("SELECT COUNT(*) c FROM Weapon"
                                 " WHERE condition_='Maintenance'")[0]["c"],
        "total_Personnel": fetch("SELECT COUNT(*) c FROM Personnel")[0]["c"],
    }

@app.get("/api/weapons")
async def get_Weapons(u=Depends(auth)):
    return fetch("""
        SELECT w.weapon_id, w.name,
               IFNULL(c.category_name,'—') AS category,
               w.serial_no, w.quantity,
               w.condition_ AS `condition`,
               w.location
        FROM   Weapon w
        LEFT JOIN Category c ON w.category_id = c.category_id
        ORDER  BY w.weapon_id
    """)

@app.post("/api/Weapons")
async def add_Weapon(w: WeaponIn, u=Depends(auth)):
    if u["role"] != "Admin":
        raise HTTPException(403,"Admin only")
    cats = fetch("SELECT category_id FROM Category"
                 " WHERE category_name=%s", (w.category,))
    cid = cats[0]["category_id"] if cats else run(
        "INSERT INTO Category(category_name) VALUES(%s)", (w.category,))
    wid = run(
        "INSERT INTO Weapon(name,category_id,serial_no,"
        "quantity,condition_,location) VALUES(%s,%s,%s,%s,%s,%s)",
        (w.name,cid,w.serial_no,w.quantity,w.condition,w.location))
    return fetch("SELECT * FROM Weapon WHERE weapon_id=%s",(wid,))[0]

@app.delete("/api/Weapons/{wid}")
async def del_Weapon(wid:int, u=Depends(auth)):
    if u["role"] != "Admin":
        raise HTTPException(403,"Admin only")
    try:
        run("DELETE FROM Weapon WHERE weapon_id=%s",(wid,))
    except mysql.connector.Error as e:
        raise HTTPException(400, e.msg)
    return {"deleted": wid}

@app.post("/api/personnel")
async def create_personnel(r: dict):

    cur = conn.cursor()

    cur.execute("""
        INSERT INTO Personnel
        (name, rank_, unit_, clearance_, contact)

        VALUES (%s,%s,%s,%s,%s)
    """, (

        r["name"],
        "Civilian",
        "Temporary",
        "LOW",
        r["contact"]

    ))

    conn.commit()

    pid = cur.lastrowid

    return {"personnel_id": pid}

@app.get("/api/personnel")
async def get_personnel():

    return fetch("""
        SELECT
            personnel_id,
            name,
            rank_,
            unit_,
            clearance,
            contact
        FROM Personnel
        ORDER BY personnel_id DESC
    """)

@app.post("/api/Personnel")
async def add_Personnel(p: PersonnelIn, u=Depends(auth)):
    if u["role"] != "Admin":
        raise HTTPException(403,"Admin only")
    pid = run(
        "INSERT INTO Personnel(name,rank_,unit_,clearance,contact)"
        " VALUES(%s,%s,%s,%s,%s)",
        (p.name,p.rank,p.unit,p.clearance,p.contact))
    return fetch("SELECT * FROM Personnel WHERE personnel_id=%s",(pid,))[0]

@app.get("/api/issues")
async def get_issues():

    return fetch("""

        SELECT
            i.issue_id,
            w.name AS weapon_name,
            p.name AS officer_name,
            DATE_FORMAT(i.issue_date,'%Y-%m-%d') AS issue_date,
            DATE_FORMAT(i.return_date,'%Y-%m-%d') AS return_date,
            i.status_ AS status

        FROM Issue i

        LEFT JOIN Weapon w
        ON i.weapon_id = w.weapon_id

        LEFT JOIN Personnel p
        ON i.personnel_id = p.personnel_id

        ORDER BY i.issue_id DESC

    """)


@app.get("/api/issues")
async def get_issues():

    return fetch("""
        SELECT
            i.issue_id,
            w.name AS weapon_name,
            p.name AS officer_name,
            DATE_FORMAT(i.issue_date,'%Y-%m-%d') AS issue_date,
            DATE_FORMAT(i.return_date,'%Y-%m-%d') AS return_date,
            i.status_ AS status

        FROM Issue i

        LEFT JOIN Weapon w
        ON i.weapon_id = w.weapon_id

        LEFT JOIN Personnel p
        ON i.personnel_id = p.personnel_id

        ORDER BY i.issue_id DESC
    """)


@app.post("/api/issues")
async def create_issue(r: IssueIn, u=Depends(auth)):

    try:
        call_proc("sp_Issue",(r.weapon_id, r.personnel_id))

    except mysql.connector.Error as e:
        raise HTTPException(400, e.msg)

    return {"message":"Issued via stored procedure ✓"}
@app.post("/api/Maintenance")
async def add_maint(r: MaintIn, u=Depends(auth)):
    mid = run("""
        INSERT INTO Maintenance
            (weapon_id,tech_id,date_logged,type_,outcome,next_due)
        VALUES
            (%s,%s,CURDATE(),%s,'IN PROGRESS',
             DATE_ADD(CURDATE(),INTERVAL 180 DAY))
    """, (r.weapon_id, r.tech_id, r.type))
    run("UPDATE Weapon SET condition_='Maintenance'"
        " WHERE weapon_id=%s",(r.weapon_id,))
    return {"maint_id":mid,"message":"Logged ✓"}

@app.get("/api/audit")
async def get_audit(u=Depends(auth)):
    return fetch("""
        SELECT log_id, action_, tbl AS table_name,
               record_id, description,
               DATE_FORMAT(logged_at,'%Y-%m-%d %H:%i:%s') AS logged_at
        FROM   AuditLog
        ORDER  BY log_id DESC
        LIMIT  100
    """)

@app.post("/api/query")
async def run_query(r: QueryIn, u=Depends(auth)):
    sql   = r.query.strip()
    first = sql.split()[0].upper() if sql else ""
    if first not in ("SELECT","SHOW","DESCRIBE","DESC","EXPLAIN"):
        raise HTTPException(400,
            "Only SELECT / SHOW / DESCRIBE allowed in terminal")
    t0 = time.time()
    try:
        rows = fetch(sql)
        return {
            "rows":         rows,
            "row_count":    len(rows),
            "execution_ms": round((time.time()-t0)*1000,2)
        }
    except Exception as e:
        raise HTTPException(400,str(e))

# ══════════════════════════════════════════════════
#  SERVE FRONTEND PAGES
# ══════════════════════════════════════════════════
_root = os.path.join(os.path.dirname(os.path.abspath(__file__)),"..")

@app.get("/")
async def page_login():
    return FileResponse(os.path.join(_root,"login.html"))

@app.get("/home")
async def page_home():
    return FileResponse(os.path.join(_root,"index.html"))

@app.get("/dashboard")
async def page_dashboard():
    return FileResponse(os.path.join(_root,"dashboard.html"))

# ══════════════════════════════════════════════════
#  STARTUP
# ══════════════════════════════════════════════════
@app.on_event("startup")
async def on_start():
    print("  Connecting to local MySQL → Weapon_arsenal ...")
    setup()
    print("  WAIMS ready → http://localhost:8000")
    from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for testing, later restrict to frontend URL
    allow_methods=["*"],
    allow_headers=["*"]
)
