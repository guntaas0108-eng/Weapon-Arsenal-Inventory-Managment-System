-- ============================================================
--  WAIMS — Weapon Arsenal Inventory Management System
--  Complete MySQL Setup Script
--  Course: UCS310 — DBMS | Thapar Institute
--  Run this entire file in MySQL Workbench
-- ============================================================

-- ══ 1. CREATE & SELECT DATABASE ══════════════════════════════
DROP DATABASE IF EXISTS waims;
CREATE DATABASE waims CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE waims;

-- ══ 2. CREATE TABLES (DDL) ════════════════════════════════════

-- 2.1 Category Table
CREATE TABLE Category (
    category_id    INT          PRIMARY KEY AUTO_INCREMENT,
    category_name  VARCHAR(40)  NOT NULL,
    description    VARCHAR(200),
    class_level    VARCHAR(20)
);

-- 2.2 Weapon Table
CREATE TABLE Weapon (
    weapon_id   INT          PRIMARY KEY AUTO_INCREMENT,
    name        VARCHAR(50)  NOT NULL,
    category_id INT,
    serial_no   VARCHAR(30)  NOT NULL UNIQUE,
    quantity    INT          DEFAULT 1 CHECK (quantity >= 0),
    condition_  VARCHAR(20)  CHECK (condition_ IN ('Operational','Maintenance','Decommissioned')),
    location    VARCHAR(40),
    FOREIGN KEY (category_id) REFERENCES Category(category_id)
);

-- 2.3 Personnel Table
CREATE TABLE Personnel (
    personnel_id INT          PRIMARY KEY AUTO_INCREMENT,
    name         VARCHAR(80)  NOT NULL,
    rank_        VARCHAR(30),
    unit_        VARCHAR(50),
    clearance    VARCHAR(20),
    contact      VARCHAR(15)
);

-- 2.4 Issue Table
CREATE TABLE Issue (
    issue_id      INT          PRIMARY KEY AUTO_INCREMENT,
    weapon_id     INT,
    personnel_id  INT,
    issue_date    DATE         DEFAULT (CURRENT_DATE),
    return_date   DATE,
    status_       VARCHAR(12)  DEFAULT 'ISSUED',
    FOREIGN KEY (weapon_id)    REFERENCES Weapon(weapon_id),
    FOREIGN KEY (personnel_id) REFERENCES Personnel(personnel_id)
);

-- 2.5 Maintenance Table
CREATE TABLE Maintenance (
    maintenance_id INT         PRIMARY KEY AUTO_INCREMENT,
    weapon_id      INT,
    tech_id        VARCHAR(20),
    date_logged    DATE        DEFAULT (CURRENT_DATE),
    type_          VARCHAR(40),
    outcome        VARCHAR(20) DEFAULT 'IN PROGRESS',
    next_due       DATE,
    FOREIGN KEY (weapon_id) REFERENCES Weapon(weapon_id)
);

-- 2.6 Audit Log Table (for trigger records)
CREATE TABLE AuditLog (
    log_id      INT          PRIMARY KEY AUTO_INCREMENT,
    action_     VARCHAR(20),
    table_name  VARCHAR(30),
    record_id   INT,
    description VARCHAR(200),
    logged_at   DATETIME     DEFAULT CURRENT_TIMESTAMP
);

-- ══ 3. INSERT SAMPLE DATA (DML) ═══════════════════════════════

-- Categories
INSERT INTO Category (category_name, description, class_level) VALUES
('Assault Rifle', 'Standard infantry rifles', 'CONFIDENTIAL'),
('Pistol',        'Sidearm handguns',         'RESTRICTED'),
('Sniper Rifle',  'Long-range precision rifles','SECRET'),
('SMG',           'Submachine guns',           'CONFIDENTIAL'),
('LMG',           'Light machine guns',        'SECRET');

-- Weapons
INSERT INTO Weapon (name, category_id, serial_no, quantity, condition_, location) VALUES
('AK-47',        1, 'AK-2021-001', 45, 'Operational',    'Bay A-1'),
('INSAS Rifle',  1, 'IN-2019-022', 30, 'Operational',    'Bay A-2'),
('Glock 19',     2, 'GL-2022-007', 80, 'Operational',    'Bay B-1'),
('SIG Sauer P320',2,'SG-2020-014', 25, 'Maintenance',    'Bay B-2'),
('L96 Sniper',   3, 'L9-2018-003', 10, 'Operational',    'Bay C-1'),
('MP5',          4, 'MP-2023-011', 20, 'Operational',    'Bay D-1'),
('M16A4',        1, 'M1-2017-088',  0, 'Decommissioned', 'Storage E-9');

-- Personnel
INSERT INTO Personnel (name, rank_, unit_, clearance, contact) VALUES
('Col. Arjun Sharma',  'Colonel',    'Alpha Battalion',  'TOP SECRET',   '9810001234'),
('Maj. Priya Nair',    'Major',      'Bravo Company',    'SECRET',       '9820005678'),
('Lt. Rajan Verma',    'Lieutenant', 'Charlie Platoon',  'CONFIDENTIAL', '9830009012'),
('Sgt. Amit Yadav',    'Sergeant',   'Delta Squad',      'CONFIDENTIAL', '9840003456'),
('Cpl. Sunita Devi',   'Corporal',   'Echo Unit',        'RESTRICTED',   '9850007890');

-- Issues
INSERT INTO Issue (weapon_id, personnel_id, issue_date, return_date, status_) VALUES
(1, 1, '2025-03-01', NULL,         'ISSUED'),
(3, 2, '2025-03-10', '2025-03-25', 'RETURNED'),
(5, 3, '2025-04-01', NULL,         'ISSUED'),
(6, 4, '2025-02-15', '2025-02-28', 'RETURNED'),
(2, 1, '2025-01-10', NULL,         'OVERDUE');

-- Maintenance
INSERT INTO Maintenance (weapon_id, tech_id, date_logged, type_, outcome, next_due) VALUES
(4, 'TECH-04', '2025-04-01', 'Scheduled Inspection', 'IN PROGRESS', '2025-10-01'),
(1, 'TECH-02', '2025-02-15', 'Cleaning',             'COMPLETED',   '2025-08-15'),
(7, 'TECH-01', '2025-01-20', 'Decommission Audit',   'COMPLETED',   NULL),
(5, 'TECH-03', '2025-03-05', 'Scope Calibration',    'COMPLETED',   '2025-09-05');

-- ══ 4. STORED PROCEDURES ═════════════════════════════════════

DELIMITER $$

-- Procedure 1: Issue a weapon to personnel
CREATE PROCEDURE issue_weapon(
    IN p_weapon_id    INT,
    IN p_personnel_id INT
)
BEGIN
    DECLARE v_qty   INT;
    DECLARE v_cond  VARCHAR(20);

    -- Read current weapon state
    SELECT quantity, condition_
    INTO   v_qty, v_cond
    FROM   Weapon
    WHERE  weapon_id = p_weapon_id
    FOR UPDATE;

    -- Validate
    IF v_qty < 1 OR v_cond != 'Operational' THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Weapon unavailable for issue';
    END IF;

    -- Insert issue record
    INSERT INTO Issue (weapon_id, personnel_id, issue_date, status_)
    VALUES (p_weapon_id, p_personnel_id, CURRENT_DATE, 'ISSUED');

    -- Decrement quantity
    UPDATE Weapon
    SET    quantity = quantity - 1
    WHERE  weapon_id = p_weapon_id;

    -- Log to audit
    INSERT INTO AuditLog (action_, table_name, record_id, description)
    VALUES ('INSERT', 'Issue', LAST_INSERT_ID(),
            CONCAT('Weapon ', p_weapon_id, ' issued to personnel ', p_personnel_id));
END$$

-- Procedure 2: Return a weapon
CREATE PROCEDURE return_weapon(
    IN p_issue_id INT
)
BEGIN
    DECLARE v_weapon_id INT;
    DECLARE v_status    VARCHAR(12);

    SELECT weapon_id, status_
    INTO   v_weapon_id, v_status
    FROM   Issue
    WHERE  issue_id = p_issue_id;

    IF v_status = 'RETURNED' THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Weapon already returned';
    END IF;

    UPDATE Issue
    SET    return_date = CURRENT_DATE, status_ = 'RETURNED'
    WHERE  issue_id = p_issue_id;

    UPDATE Weapon
    SET    quantity = quantity + 1
    WHERE  weapon_id = v_weapon_id;

    INSERT INTO AuditLog (action_, table_name, record_id, description)
    VALUES ('UPDATE', 'Issue', p_issue_id,
            CONCAT('Weapon ', v_weapon_id, ' returned'));
END$$

-- Procedure 3: Full inventory report
CREATE PROCEDURE inventory_report()
BEGIN
    SELECT w.weapon_id, w.name, c.category_name,
           w.serial_no, w.quantity, w.condition_, w.location
    FROM   Weapon w
    JOIN   Category c ON w.category_id = c.category_id
    ORDER BY c.category_name, w.name;
END$$

DELIMITER ;

-- ══ 5. FUNCTIONS ══════════════════════════════════════════════

DELIMITER $$

-- Function 1: Get total operational stock for a category
CREATE FUNCTION get_category_stock(p_category_id INT)
RETURNS INT
READS SQL DATA
DETERMINISTIC
BEGIN
    DECLARE v_total INT;
    SELECT IFNULL(SUM(quantity), 0)
    INTO   v_total
    FROM   Weapon
    WHERE  category_id = p_category_id
      AND  condition_  = 'Operational';
    RETURN v_total;
END$$

-- Function 2: Check if weapon is due for maintenance
CREATE FUNCTION is_maintenance_due(p_weapon_id INT)
RETURNS VARCHAR(15)
READS SQL DATA
DETERMINISTIC
BEGIN
    DECLARE v_last DATE;
    SELECT MAX(date_logged)
    INTO   v_last
    FROM   Maintenance
    WHERE  weapon_id = p_weapon_id;

    IF v_last IS NULL OR DATEDIFF(CURRENT_DATE, v_last) > 180 THEN
        RETURN 'OVERDUE';
    ELSE
        RETURN 'OK';
    END IF;
END$$

DELIMITER ;

-- ══ 6. TRIGGERS ════════════════════════════════════════════════

DELIMITER $$

-- Trigger 1: After issuing a weapon — auto-schedule maintenance if overdue
CREATE TRIGGER trg_maintenance_check
AFTER INSERT ON Issue
FOR EACH ROW
BEGIN
    DECLARE v_last DATE;

    SELECT MAX(date_logged)
    INTO   v_last
    FROM   Maintenance
    WHERE  weapon_id = NEW.weapon_id;

    IF v_last IS NULL OR DATEDIFF(CURRENT_DATE, v_last) > 180 THEN
        INSERT INTO Maintenance (weapon_id, tech_id, date_logged, type_, outcome, next_due)
        VALUES (NEW.weapon_id, 'AUTO', CURRENT_DATE,
                'Scheduled Inspection', 'PENDING',
                DATE_ADD(CURRENT_DATE, INTERVAL 14 DAY));

        INSERT INTO AuditLog (action_, table_name, record_id, description)
        VALUES ('TRIGGER', 'Maintenance', NEW.weapon_id,
                CONCAT('Auto-scheduled maintenance for weapon ', NEW.weapon_id));
    END IF;
END$$

-- Trigger 2: Before updating Issue — auto-flag overdue returns
CREATE TRIGGER trg_overdue_flag
BEFORE UPDATE ON Issue
FOR EACH ROW
BEGIN
    IF NEW.return_date IS NULL
       AND DATEDIFF(CURRENT_DATE, OLD.issue_date) > 30
       AND NEW.status_ != 'RETURNED'
    THEN
        SET NEW.status_ = 'OVERDUE';
    END IF;
END$$

-- Trigger 3: After weapon condition changes — log to audit
CREATE TRIGGER trg_weapon_condition_change
AFTER UPDATE ON Weapon
FOR EACH ROW
BEGIN
    IF OLD.condition_ != NEW.condition_ THEN
        INSERT INTO AuditLog (action_, table_name, record_id, description)
        VALUES ('UPDATE', 'Weapon', NEW.weapon_id,
                CONCAT('Condition changed: ', OLD.condition_, ' → ', NEW.condition_));
    END IF;
END$$

-- Trigger 4: Before deleting a weapon — prevent if actively issued
CREATE TRIGGER trg_prevent_delete_issued
BEFORE DELETE ON Weapon
FOR EACH ROW
BEGIN
    DECLARE v_count INT;
    SELECT COUNT(*) INTO v_count
    FROM   Issue
    WHERE  weapon_id = OLD.weapon_id
      AND  status_   IN ('ISSUED', 'OVERDUE');

    IF v_count > 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Cannot delete weapon: currently issued to personnel';
    END IF;
END$$

DELIMITER ;

-- ══ 7. VIEWS ══════════════════════════════════════════════════

-- View 1: Active issues with full details
CREATE OR REPLACE VIEW vw_active_issues AS
SELECT i.issue_id, w.name AS weapon, w.serial_no,
       p.name AS officer, p.rank_, p.clearance,
       i.issue_date, i.status_,
       DATEDIFF(CURRENT_DATE, i.issue_date) AS days_out
FROM   Issue i
JOIN   Weapon w    ON i.weapon_id    = w.weapon_id
JOIN   Personnel p ON i.personnel_id = p.personnel_id
WHERE  i.status_ IN ('ISSUED', 'OVERDUE');

-- View 2: Operational stock summary
CREATE OR REPLACE VIEW vw_operational_stock AS
SELECT w.weapon_id, w.name, c.category_name,
       w.quantity, w.location,
       is_maintenance_due(w.weapon_id) AS maint_status
FROM   Weapon w
JOIN   Category c ON w.category_id = c.category_id
WHERE  w.condition_ = 'Operational';

-- View 3: Maintenance due report
CREATE OR REPLACE VIEW vw_maintenance_due AS
SELECT w.name AS weapon, m.tech_id, m.type_,
       m.next_due,
       DATEDIFF(CURRENT_DATE, m.next_due) AS days_overdue
FROM   Maintenance m
JOIN   Weapon w ON m.weapon_id = w.weapon_id
WHERE  m.next_due < CURRENT_DATE
  AND  m.outcome != 'COMPLETED';

-- ══ 8. VERIFY — SELECT QUERIES ════════════════════════════════

-- All tables
SELECT * FROM Category;
SELECT * FROM Weapon;
SELECT * FROM Personnel;
SELECT * FROM Issue;
SELECT * FROM Maintenance;

-- Joins: issued weapons with officer details
SELECT w.name AS weapon, p.name AS officer, p.rank_,
       i.issue_date, i.status_
FROM   Issue i
JOIN   Weapon    w ON i.weapon_id    = w.weapon_id
JOIN   Personnel p ON i.personnel_id = p.personnel_id
ORDER BY i.issue_date DESC;

-- Aggregate: stock by category
SELECT c.category_name,
       COUNT(w.weapon_id)  AS weapon_types,
       SUM(w.quantity)     AS total_units,
       AVG(w.quantity)     AS avg_stock
FROM   Weapon w
JOIN   Category c ON w.category_id = c.category_id
GROUP BY c.category_name
HAVING SUM(w.quantity) > 0
ORDER BY total_units DESC;

-- Subquery: weapons never maintained
SELECT name, condition_
FROM   Weapon
WHERE  weapon_id NOT IN (SELECT DISTINCT weapon_id FROM Maintenance);

-- Function usage
SELECT name, get_category_stock(category_id) AS op_stock
FROM   Category;

-- View usage
SELECT * FROM vw_active_issues;
SELECT * FROM vw_operational_stock;

-- Test procedure: issue weapon 3 to personnel 5
CALL issue_weapon(3, 5);

-- Check audit log
SELECT * FROM AuditLog ORDER BY logged_at DESC;

-- Test trigger fired check
SELECT * FROM Maintenance ORDER BY maintenance_id DESC LIMIT 3;
DROP DATABASE waims;
CREATE DATABASE waims;
USE waims;

USE waims;
SELECT * FROM Issue;

SELECT * FROM Issue ORDER BY Issue_id DESC;

SELECT * FROM Issue;
SELECT * FROM Personnel;

USE waims;
SELECT * FROM Issue ORDER BY Issue_id DESC;

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
ORDER BY i.issue_id DESC;