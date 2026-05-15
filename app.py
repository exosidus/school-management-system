from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
)
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
from datetime import datetime, date
from functools import wraps

app = Flask(__name__)
app.secret_key = "your-secret-key-change-in-production"

DATABASE = "eschool.db"


# Custom Jinja2 filter for safe date formatting
@app.template_filter("dateformat")
def dateformat(value, format="%Y-%m-%d"):
    if value is None:
        return "N/A"
    if isinstance(value, str):
        return value  # Return string as-is
    try:
        return value.strftime(format)
    except:
        return str(value)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


def role_required(roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "role" not in session or session["role"] not in roles:
                flash("Access denied")
                return redirect(url_for("index"))
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    with open("schema.sql", "r") as f:
        conn.executescript(f.read())
    conn.close()


@app.route("/")
@login_required
def index():
    conn = get_db_connection()
    stats = {
        "students": conn.execute("SELECT COUNT(*) as count FROM students").fetchone()[
            "count"
        ],
        "teachers": conn.execute("SELECT COUNT(*) as count FROM teachers").fetchone()[
            "count"
        ],
        "subjects": conn.execute("SELECT COUNT(*) as count FROM subjects").fetchone()[
            "count"
        ],
        "classes": conn.execute("SELECT COUNT(*) as count FROM classes").fetchone()[
            "count"
        ],
    }
    conn.close()
    return render_template("dashboard.html", stats=stats)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        if user and check_password_hash(user["password"], password):
            # Check if account is approved
            if user["status"] != "active":
                if user["status"] == "pending":
                    flash(
                        "Your account is pending approval. Please contact the administrator."
                    )
                else:
                    flash(
                        "Your account has been deactivated. Please contact the administrator."
                    )
                conn.close()
                return render_template("login.html")

            # Get user role
            user_role = conn.execute(
                """SELECT r.role_name FROM user_roles ur 
                   JOIN roles r ON ur.role_id = r.id 
                   WHERE ur.user_id = ? LIMIT 1""",
                (user["id"],),
            ).fetchone()

            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user_role["role_name"] if user_role else "student"
            
            # Check if user needs to change password (temporary password)
            if check_password_hash(user["password"], "Temp2024!"):
                session["must_change_password"] = True
                conn.close()
                return redirect(url_for("force_change_password"))
            
            conn.close()
            return redirect(url_for("index"))
        else:
            flash("Invalid username or password")

        conn.close()

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
@login_required
@role_required(["admin"])
def register():
    if request.method == "POST":
        person_type = request.form["person_type"]
        person_id = request.form["person_id"]
        username = request.form["username"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        # Validation
        if password != confirm_password:
            flash("Passwords do not match")
            return render_template("register.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters long")
            return render_template("register.html")

        conn = get_db_connection()

        # Check if username exists
        existing_user = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing_user:
            flash("Username already exists")
            conn.close()
            return render_template("register.html")

        # Fetch person information based on type
        person_info = None
        role_name = None
        
        if person_type == "student":
            person_info = conn.execute(
                "SELECT * FROM students WHERE id = ?", (person_id,)
            ).fetchone()
            role_name = "student"
        elif person_type == "teacher":
            person_info = conn.execute(
                "SELECT * FROM teachers WHERE id = ?", (person_id,)
            ).fetchone()
            role_name = "teacher"
        elif person_type == "parent":
            # For parents, we'll use basic info from form
            role_name = "parent"

        if not person_info and person_type != "parent":
            flash(f"{person_type.title()} not found")
            conn.close()
            return render_template("register.html")

        # Create user account
        hashed_password = generate_password_hash(password)
        try:
            # Use existing info or form data
            first_name = request.form.get("first_name", "")
            last_name = request.form.get("last_name", "")
            email = request.form.get("email", "")
            phone = request.form.get("phone", "")
            
            cursor = conn.execute(
                "INSERT INTO users (username, password, first_name, last_name, email, phone) VALUES (?, ?, ?, ?, ?, ?)",
                (username, hashed_password, first_name, last_name, email, phone),
            )
            user_id = cursor.lastrowid

            # Assign role
            role = conn.execute(
                'SELECT id FROM roles WHERE role_name = ?', (role_name,)
            ).fetchone()
            conn.execute(
                "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
                (user_id, role["id"]),
            )
            
            # Link to existing record
            if person_type == "student":
                conn.execute(
                    "UPDATE students SET user_id = ? WHERE id = ?",
                    (user_id, person_id)
                )
            elif person_type == "teacher":
                conn.execute(
                    "UPDATE teachers SET user_id = ? WHERE id = ?",
                    (user_id, person_id)
                )

            conn.commit()
            flash(
                f"Account created successfully for {person_type}! The account is pending approval."
            )
            conn.close()
            return redirect(url_for("manage_accounts"))
        except Exception as e:
            flash("Error creating account. Please try again.")
            conn.close()
            return render_template("register.html")

    # Get available students and teachers for dropdown
    conn = get_db_connection()
    students = conn.execute(
        "SELECT s.id, s.student_id FROM students s WHERE s.user_id IS NULL"
    ).fetchall()
    teachers = conn.execute(
        """SELECT t.id, t.teacher_id, t.subject FROM teachers t 
           WHERE t.user_id IS NULL"""
    ).fetchall()
    conn.close()
    
    return render_template("register.html", students=students, teachers=teachers)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/students")
@login_required
@role_required(["admin", "director", "teacher"])
def students():
    conn = get_db_connection()
    search = request.args.get('search', '')
    grade = request.args.get('grade', '')
    section = request.args.get('section', '')
    
    query = """SELECT s.*, u.first_name, u.last_name, u.phone FROM students s 
               LEFT JOIN users u ON s.user_id = u.id 
               WHERE 1=1"""
    params = []
    
    if search:
        query += " AND (u.first_name LIKE ? OR u.last_name LIKE ? OR s.student_id LIKE ?)"
        params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])
    if grade:
        query += " AND s.grade = ?"
        params.append(grade)
    if section:
        query += " AND s.section = ?"
        params.append(section)
        
    query += " ORDER BY u.first_name, u.last_name"
    
    students = conn.execute(query, params).fetchall()
    conn.close()
    return render_template("students.html", students=students, search=search, grade=grade, section=section)


@app.route("/add_student", methods=["GET", "POST"])
@login_required
@role_required(["admin", "director", "teacher"])
def add_student():
    if request.method == "POST":
        conn = get_db_connection()
        # Generate student_id automatically in STU-0000001 format
        max_id_row = conn.execute('SELECT MAX(id) as max_id FROM students').fetchone()
        max_id = max_id_row['max_id'] if max_id_row and max_id_row['max_id'] else 0
        student_id = f"STU-{max_id + 1:07d}"
        
        # Create user record first
        cursor = conn.execute(
            "INSERT INTO users (first_name, last_name, email, phone, username, password, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                request.form["first_name"],
                request.form["last_name"],
                request.form.get("email", ""),
                request.form.get("phone", ""),
                student_id.lower(),
                generate_password_hash("Temp2024!"),
                "active"
            ),
        )
        user_id = cursor.lastrowid
        
        # Assign student role
        role = conn.execute('SELECT id FROM roles WHERE role_name = "student"').fetchone()
        conn.execute(
            "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (user_id, role["id"]),
        )
        
        # Create student record
        conn.execute(
            "INSERT INTO students (user_id, student_id, grade, section, parent_phone, address, birth_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                student_id,
                request.form["grade"],
                request.form["section"],
                request.form["parent_phone"],
                request.form["address"],
                request.form["birth_date"],
            ),
        )
        conn.commit()
        conn.close()
        flash(f"Student added successfully with ID: {student_id}")
        return redirect(url_for("students"))

    return render_template("add_student.html")


@app.route("/teachers")
@login_required
@role_required(["admin", "director", "teacher"])
def teachers():
    conn = get_db_connection()
    teachers = conn.execute(
        """SELECT t.*, u.first_name, u.last_name, u.email, u.phone,
           (SELECT COUNT(*) FROM classes c WHERE c.teacher_id = t.id) as class_count,
           (SELECT COUNT(DISTINCT s.id) FROM students s 
            JOIN classes c ON s.grade = c.grade AND s.section = c.section 
            WHERE c.teacher_id = t.id) as student_count
           FROM teachers t 
           LEFT JOIN users u ON t.user_id = u.id 
           ORDER BY u.last_name"""
    ).fetchall()
    total_classes = conn.execute("SELECT COUNT(*) as count FROM classes").fetchone()['count']
    conn.close()
    return render_template("teachers.html", teachers=teachers, total_classes=total_classes)


@app.route("/teacher_profile/<int:teacher_id>")
@login_required
@role_required(["admin", "director", "teacher"])
def teacher_profile(teacher_id):
    conn = get_db_connection()
    teacher = conn.execute(
        """SELECT t.*, u.first_name, u.last_name, u.email, u.phone 
           FROM teachers t 
           LEFT JOIN users u ON t.user_id = u.id 
           WHERE t.id = ?""", (teacher_id,)
    ).fetchone()
    
    classes = conn.execute(
        """SELECT c.*, s.subject_name,
           (SELECT COUNT(*) FROM students st WHERE st.grade = c.grade AND st.section = c.section) as student_count
           FROM classes c 
           LEFT JOIN subjects s ON c.subject_id = s.id 
           WHERE c.teacher_id = ?""", (teacher_id,)
    ).fetchall()
    
    total_students = sum(c['student_count'] for c in classes)
    subjects = list(set(c['subject_name'] for c in classes if c['subject_name']))
    
    avg_grade = conn.execute(
        """SELECT AVG(g.score/g.max_score*100) as avg FROM grades g 
           JOIN classes c ON g.subject_id = c.subject_id 
           WHERE c.teacher_id = ?""", (teacher_id,)
    ).fetchone()['avg']
    
    conn.close()
    return render_template("teacher_profile.html", teacher=teacher, classes=classes, 
                         total_students=total_students, subjects=subjects, 
                         avg_grade=round(avg_grade, 2) if avg_grade else None)


@app.route("/teacher_reports")
@login_required
@role_required(["admin", "director"])
def teacher_reports():
    conn = get_db_connection()
    
    # Summary statistics
    summary = conn.execute(
        """SELECT 
           (SELECT COUNT(*) FROM teachers) as total_teachers,
           (SELECT COUNT(*) FROM teachers WHERE status = 'active') as active_teachers,
           (SELECT COUNT(*) FROM classes) as total_classes,
           (SELECT COUNT(*) FROM students) as total_students"""
    ).fetchone()
    
    # Subject statistics
    subject_stats = conn.execute(
        """SELECT t.subject as subject_name, 
           COUNT(DISTINCT t.id) as teacher_count,
           COUNT(DISTINCT c.id) as class_count
           FROM teachers t 
           LEFT JOIN classes c ON t.id = c.teacher_id 
           GROUP BY t.subject
           ORDER BY teacher_count DESC"""
    ).fetchall()
    
    # Workload statistics
    workload_stats = conn.execute(
        """SELECT t.*, u.first_name, u.last_name,
           COUNT(DISTINCT c.id) as class_count,
           COUNT(DISTINCT s.id) as student_count
           FROM teachers t 
           LEFT JOIN users u ON t.user_id = u.id
           LEFT JOIN classes c ON t.id = c.teacher_id
           LEFT JOIN students s ON s.grade = c.grade AND s.section = c.section
           WHERE t.status = 'active'
           GROUP BY t.id
           ORDER BY student_count DESC"""
    ).fetchall()
    
    # Performance statistics
    performance_stats = conn.execute(
        """SELECT t.*, u.first_name, u.last_name,
           COUNT(DISTINCT c.id) as class_count,
           COUNT(DISTINCT s.id) as student_count,
           AVG(g.score/g.max_score*100) as avg_grade
           FROM teachers t 
           LEFT JOIN users u ON t.user_id = u.id
           LEFT JOIN classes c ON t.id = c.teacher_id
           LEFT JOIN students s ON s.grade = c.grade AND s.section = c.section
           LEFT JOIN grades g ON g.subject_id = c.subject_id AND g.student_id = s.id
           GROUP BY t.id
           ORDER BY avg_grade DESC"""
    ).fetchall()
    
    conn.close()
    return render_template("teacher_reports.html", summary=summary, subject_stats=subject_stats,
                         workload_stats=workload_stats, performance_stats=performance_stats)


@app.route("/add_teacher", methods=["GET", "POST"])
@login_required
@role_required(["admin", "director"])
def add_teacher():
    if request.method == "POST":
        conn = get_db_connection()
        # Generate teacher_id automatically
        max_id_row = conn.execute('SELECT MAX(id) as max_id FROM teachers').fetchone()
        max_id = max_id_row['max_id'] if max_id_row and max_id_row['max_id'] else 0
        teacher_id = f"TCH-{max_id + 1:07d}"
        
        # Create user record first
        cursor = conn.execute(
            "INSERT INTO users (first_name, last_name, email, phone, username, password, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                request.form["first_name"],
                request.form["last_name"],
                request.form.get("email", ""),
                request.form.get("phone", ""),
                teacher_id.lower(),
                generate_password_hash("Temp2024!"),
                "pending"
            ),
        )
        user_id = cursor.lastrowid
        
        # Assign teacher role
        role = conn.execute('SELECT id FROM roles WHERE role_name = "teacher"').fetchone()
        conn.execute(
            "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (user_id, role["id"]),
        )
        
        # Create teacher record
        conn.execute(
            "INSERT INTO teachers (user_id, teacher_id, subject, qualification, hire_date) VALUES (?, ?, ?, ?, ?)",
            (
                user_id,
                teacher_id,
                request.form["subject"],
                request.form["qualification"],
                request.form["hire_date"],
            ),
        )
        conn.commit()
        conn.close()
        flash(f"Teacher added successfully with ID: {teacher_id}")
        return redirect(url_for("teachers"))

    conn = get_db_connection()
    subjects = conn.execute("SELECT DISTINCT subject_name FROM subjects").fetchall()
    conn.close()
    return render_template("add_teacher.html", subjects=subjects)


@app.route("/grades")
@login_required
def grades():
    conn = get_db_connection()
    if session["role"] == "student":
        grades = conn.execute(
            """SELECT g.*, s.subject_name, u.first_name, u.last_name 
               FROM grades g 
               JOIN subjects s ON g.subject_id = s.id 
               JOIN students st ON g.student_id = st.id 
               LEFT JOIN users u ON st.user_id = u.id 
               WHERE st.id = ?""",
            (session["user_id"],),
        ).fetchall()
    elif session["role"] == "teacher":
        teacher = conn.execute(
            "SELECT id FROM teachers WHERE user_id = ?", (session["user_id"],)
        ).fetchone()
        if teacher:
            grades = conn.execute(
                """SELECT g.*, s.subject_name, u.first_name, u.last_name 
                   FROM grades g 
                   JOIN subjects s ON g.subject_id = s.id 
                   JOIN students st ON g.student_id = st.id 
                   LEFT JOIN users u ON st.user_id = u.id 
                   JOIN classes c ON st.grade = c.grade AND st.section = c.section 
                   WHERE c.teacher_id = ? ORDER BY u.first_name, u.last_name, g.date_recorded DESC""",
                (teacher["id"],),
            ).fetchall()
        else:
            grades = []
    else:
        grades = conn.execute(
            """SELECT g.*, s.subject_name, u.first_name, u.last_name 
               FROM grades g 
               JOIN subjects s ON g.subject_id = s.id 
               JOIN students st ON g.student_id = st.id 
               LEFT JOIN users u ON st.user_id = u.id 
               ORDER BY u.first_name, u.last_name, g.date_recorded DESC"""
        ).fetchall()
    conn.close()
    return render_template("grades.html", grades=grades)


@app.route("/add_grade", methods=["GET", "POST"])
@login_required
@role_required(["admin", "director", "teacher"])
def add_grade():
    if request.method == "POST":
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO grades (student_id, subject_id, assessment_type, score, max_score) VALUES (?, ?, ?, ?, ?)",
            (
                request.form["student_id"],
                request.form["subject_id"],
                request.form["assessment_type"],
                request.form["score"],
                request.form["max_score"],
            ),
        )
        conn.commit()
        conn.close()
        flash("Grade added successfully")
        return redirect(url_for("grades"))

    # Get pre-selected student from URL parameter
    selected_student_id = request.args.get('student_id')
    
    conn = get_db_connection()
    if session["role"] == "teacher":
        teacher = conn.execute(
            "SELECT id FROM teachers WHERE user_id = ?", (session["user_id"],)
        ).fetchone()
        if teacher:
            students = conn.execute(
                """SELECT DISTINCT s.*, u.first_name, u.last_name FROM students s 
                   LEFT JOIN users u ON s.user_id = u.id 
                   JOIN classes c ON s.grade = c.grade AND s.section = c.section 
                   WHERE c.teacher_id = ? ORDER BY u.last_name""",
                (teacher["id"],),
            ).fetchall()
            subjects = conn.execute(
                """SELECT DISTINCT sub.* FROM subjects sub 
                   JOIN classes c ON sub.id = c.subject_id 
                   WHERE c.teacher_id = ? ORDER BY sub.subject_name""",
                (teacher["id"],),
            ).fetchall()
        else:
            students = []
            subjects = []
    else:
        students = conn.execute(
            """SELECT s.*, u.first_name, u.last_name FROM students s 
               LEFT JOIN users u ON s.user_id = u.id 
               ORDER BY u.last_name"""
        ).fetchall()
        subjects = conn.execute("SELECT * FROM subjects ORDER BY subject_name").fetchall()
    conn.close()
    return render_template("add_grade.html", students=students, subjects=subjects, selected_student_id=selected_student_id)


@app.route("/attendance")
@login_required
def attendance():
    conn = get_db_connection()
    if session["role"] == "student":
        attendance = conn.execute(
            """SELECT a.*, c.class_name, s.subject_name 
               FROM attendance a 
               JOIN classes c ON a.class_id = c.id 
               JOIN subjects s ON c.subject_id = s.id 
               JOIN students st ON a.student_id = st.id 
               WHERE st.id = ? ORDER BY a.date DESC""",
            (session["user_id"],),
        ).fetchall()
    elif session["role"] == "teacher":
        teacher = conn.execute(
            "SELECT id FROM teachers WHERE user_id = ?", (session["user_id"],)
        ).fetchone()
        if teacher:
            attendance = conn.execute(
                """SELECT a.*, c.class_name, s.subject_name, u.first_name, u.last_name 
                   FROM attendance a 
                   JOIN classes c ON a.class_id = c.id 
                   JOIN subjects s ON c.subject_id = s.id 
                   JOIN students st ON a.student_id = st.id 
                   LEFT JOIN users u ON st.user_id = u.id 
                   WHERE c.teacher_id = ? ORDER BY a.date DESC""",
                (teacher["id"],),
            ).fetchall()
        else:
            attendance = []
    else:
        attendance = conn.execute(
            """SELECT a.*, c.class_name, s.subject_name, u.first_name, u.last_name 
               FROM attendance a 
               JOIN classes c ON a.class_id = c.id 
               JOIN subjects s ON c.subject_id = s.id 
               JOIN students st ON a.student_id = st.id 
               LEFT JOIN users u ON st.user_id = u.id 
               ORDER BY a.date DESC"""
        ).fetchall()
    conn.close()
    return render_template("attendance.html", attendance=attendance)


@app.route("/take_attendance", methods=["GET", "POST"])
@login_required
@role_required(["admin", "director", "teacher"])
def take_attendance():
    if request.method == "POST":
        conn = get_db_connection()
        class_id = request.form["class_id"]
        attendance_date = request.form["date"]

        # Get students in the class
        students = conn.execute(
            """SELECT s.id FROM students s 
               JOIN classes c ON s.grade = c.grade AND s.section = c.section 
               WHERE c.id = ?""",
            (class_id,),
        ).fetchall()

        for student in students:
            status = request.form.get(f'student_{student["id"]}')
            if status:
                conn.execute(
                    "INSERT OR REPLACE INTO attendance (student_id, class_id, date, status) VALUES (?, ?, ?, ?)",
                    (student["id"], class_id, attendance_date, status),
                )

        conn.commit()
        conn.close()
        flash("Attendance recorded successfully")
        return redirect(url_for("attendance"))

    conn = get_db_connection()
    if session["role"] == "teacher":
        teacher = conn.execute(
            "SELECT id FROM teachers WHERE user_id = ?", (session["user_id"],)
        ).fetchone()
        if teacher:
            classes = conn.execute(
                "SELECT * FROM classes WHERE teacher_id = ?", (teacher["id"],)
            ).fetchall()
        else:
            classes = []
    else:
        classes = conn.execute("SELECT * FROM classes").fetchall()
    conn.close()
    today = date.today().isoformat()
    return render_template("take_attendance.html", classes=classes, today=today)


@app.route("/get_class_students/<int:class_id>")
@login_required
def get_class_students(class_id):
    conn = get_db_connection()
    students = conn.execute(
        """SELECT s.* FROM students s 
           JOIN classes c ON s.grade = c.grade AND s.section = c.section 
           WHERE c.id = ?""",
        (class_id,),
    ).fetchall()
    conn.close()
    return jsonify([dict(student) for student in students])


@app.route("/classes")
@login_required
@role_required(["admin", "director", "teacher"])
def classes():
    conn = get_db_connection()
    classes = conn.execute(
        """SELECT c.*, s.subject_name, u.first_name as teacher_first, u.last_name as teacher_last 
           FROM classes c 
           LEFT JOIN subjects s ON c.subject_id = s.id 
           LEFT JOIN teachers t ON c.teacher_id = t.id 
           LEFT JOIN users u ON t.user_id = u.id 
           ORDER BY c.grade, c.section"""
    ).fetchall()
    conn.close()
    return render_template("classes.html", classes=classes)


@app.route("/add_class", methods=["GET", "POST"])
@login_required
@role_required(["admin", "director"])
def add_class():
    if request.method == "POST":
        conn = get_db_connection()
        # Generate class_name automatically
        grade = request.form["grade"]
        section = request.form["section"]
        subject = conn.execute('SELECT subject_name FROM subjects WHERE id = ?', (request.form["subject_id"],)).fetchone()
        class_name = f"{subject['subject_name']} {grade}{section}" if subject else f"Class {grade}{section}"
        
        conn.execute(
            "INSERT INTO classes (class_name, grade, section, teacher_id, subject_id, schedule) VALUES (?, ?, ?, ?, ?, ?)",
            (
                class_name,
                grade,
                section,
                request.form["teacher_id"],
                request.form["subject_id"],
                request.form["schedule"],
            ),
        )
        conn.commit()
        conn.close()
        flash(f"Class added successfully: {class_name}")
        return redirect(url_for("classes"))

    conn = get_db_connection()
    teachers = conn.execute(
        """SELECT t.*, u.first_name, u.last_name FROM teachers t 
           LEFT JOIN users u ON t.user_id = u.id 
           ORDER BY u.last_name"""
    ).fetchall()
    subjects = conn.execute("SELECT * FROM subjects ORDER BY subject_name").fetchall()
    conn.close()
    return render_template("add_class.html", teachers=teachers, subjects=subjects)


@app.route("/reports")
@login_required
@role_required(["admin", "director", "teacher"])
def reports():
    return render_template("reports.html")


@app.route("/student_report/<int:student_id>")
@login_required
def student_report(student_id):
    conn = get_db_connection()
    
    if session.get("role") == "student":
        student_check = conn.execute("SELECT id FROM students WHERE user_id = ?", (session["user_id"],)).fetchone()
        if not student_check or (student_check["id"] != student_id and session["user_id"] != student_id):
            flash("Access denied: You can only view your own report.")
            return redirect(url_for("index"))
            
    # Check if student_id is a user_id or student table id
    student = conn.execute(
        """SELECT s.*, u.first_name, u.last_name FROM students s 
           LEFT JOIN users u ON s.user_id = u.id 
           WHERE s.id = ? OR s.user_id = ?""", (student_id, student_id)
    ).fetchone()
    
    if not student:
        flash("Student not found")
        return redirect(url_for("students"))
    
    # Check if teacher can access this student
    if session["role"] == "teacher":
        teacher = conn.execute(
            "SELECT id FROM teachers WHERE user_id = ?", (session["user_id"],)
        ).fetchone()
        if teacher:
            access_check = conn.execute(
                """SELECT 1 FROM classes c 
                   WHERE c.teacher_id = ? AND c.grade = ? AND c.section = ?""",
                (teacher["id"], student["grade"], student["section"])
            ).fetchone()
            if not access_check:
                flash("Access denied - Student not in your assigned classes")
                return redirect(url_for("my_students"))
        else:
            flash("Teacher record not found")
            return redirect(url_for("index"))
    
    actual_student_id = student["id"]
    
    # Get subjects and calculate performance data
    try:
        subjects = conn.execute(
            """SELECT s.* FROM subjects s 
               JOIN subject_grades sg ON s.id = sg.subject_id 
               JOIN grade_levels gl ON sg.grade_id = gl.id 
               WHERE gl.grade_number = ? ORDER BY s.subject_name""",
            (student["grade"],)
        ).fetchall()
    except:
        # Fallback to old structure
        subjects = conn.execute(
            "SELECT * FROM subjects WHERE grade = ? ORDER BY subject_name",
            (student["grade"],)
        ).fetchall()
    
    performance_data = []
    total_average = 0
    subject_count = 0
    
    for subject in subjects:
        test1 = conn.execute(
            """SELECT AVG(score/max_score*100) as avg FROM grades 
               WHERE student_id = ? AND subject_id = ? AND assessment_type = 'test' AND notes = 'Test 1'""",
            (actual_student_id, subject["id"])
        ).fetchone()["avg"] or 0
        
        test2 = conn.execute(
            """SELECT AVG(score/max_score*100) as avg FROM grades 
               WHERE student_id = ? AND subject_id = ? AND assessment_type = 'test' AND notes = 'Test 2'""",
            (actual_student_id, subject["id"])
        ).fetchone()["avg"] or 0
        
        assignment = conn.execute(
            """SELECT AVG(score/max_score*100) as avg FROM grades 
               WHERE student_id = ? AND subject_id = ? AND assessment_type = 'assignment'""",
            (actual_student_id, subject["id"])
        ).fetchone()["avg"] or 0
        
        final = conn.execute(
            """SELECT AVG(score/max_score*100) as avg FROM grades 
               WHERE student_id = ? AND subject_id = ? AND assessment_type = 'final'""",
            (actual_student_id, subject["id"])
        ).fetchone()["avg"] or 0
        
        subject_total = (test1 * 0.2) + (test2 * 0.2) + (assignment * 0.2) + (final * 0.4)
        
        performance_data.append({
            'subject': subject["subject_name"],
            'test1': round(test1, 1),
            'test2': round(test2, 1),
            'assignment': round(assignment, 1),
            'final': round(final, 1),
            'total': round(subject_total, 1)
        })
        
        if subject_total > 0:
            total_average += subject_total
            subject_count += 1
    
    overall_average = round(total_average / subject_count, 1) if subject_count > 0 else 0
    
    # Get class ranking
    class_students = conn.execute(
        """SELECT s.id FROM students s 
           WHERE s.grade = ? AND s.section = ? AND s.status = 'active'""",
        (student["grade"], student["section"])
    ).fetchall()
    
    student_averages = []
    for class_student in class_students:
        student_total = 0
        student_subject_count = 0
        
        for subject in subjects:
            test_avg = conn.execute(
                """SELECT AVG(score/max_score*100) as avg FROM grades 
                   WHERE student_id = ? AND subject_id = ? AND assessment_type = 'test'""",
                (class_student["id"], subject["id"])
            ).fetchone()["avg"] or 0
            
            assignment_avg = conn.execute(
                """SELECT AVG(score/max_score*100) as avg FROM grades 
                   WHERE student_id = ? AND subject_id = ? AND assessment_type = 'assignment'""",
                (class_student["id"], subject["id"])
            ).fetchone()["avg"] or 0
            
            final_avg = conn.execute(
                """SELECT AVG(score/max_score*100) as avg FROM grades 
                   WHERE student_id = ? AND subject_id = ? AND assessment_type = 'final'""",
                (class_student["id"], subject["id"])
            ).fetchone()["avg"] or 0
            
            subject_avg = (test_avg * 0.4) + (assignment_avg * 0.2) + (final_avg * 0.4)
            if subject_avg > 0:
                student_total += subject_avg
                student_subject_count += 1
        
        student_overall = student_total / student_subject_count if student_subject_count > 0 else 0
        student_averages.append((class_student["id"], student_overall))
    
    student_averages.sort(key=lambda x: x[1], reverse=True)
    rank = next((i + 1 for i, (sid, _) in enumerate(student_averages) if sid == actual_student_id), 0)
    total_students = len(student_averages)
    
    attendance = conn.execute(
        """SELECT COUNT(*) as total, 
           SUM(CASE WHEN status = "present" THEN 1 ELSE 0 END) as present 
           FROM attendance WHERE student_id = ?""",
        (actual_student_id,),
    ).fetchone()
    
    conn.close()
    return render_template(
        "student_report.html", 
        student=student, 
        performance_data=performance_data,
        overall_average=overall_average,
        rank=rank,
        total_students=total_students,
        attendance=attendance
    )


@app.route("/profile")
@login_required
def profile():
    conn = get_db_connection()
    if session["role"] == "student":
        user_data = conn.execute(
            "SELECT * FROM students WHERE id = ?", (session["user_id"],)
        ).fetchone()
    elif session["role"] == "teacher":
        user_data = conn.execute(
            "SELECT * FROM teachers WHERE id = ?", (session["user_id"],)
        ).fetchone()
    else:
        user_data = conn.execute(
            "SELECT * FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()
    conn.close()
    return render_template("profile.html", user_data=user_data)


@app.route("/api/students")
@login_required
def api_students():
    conn = get_db_connection()
    students = conn.execute(
        """SELECT s.id, s.student_id, u.first_name, u.last_name FROM students s 
           LEFT JOIN users u ON s.user_id = u.id 
           ORDER BY u.last_name"""
    ).fetchall()
    conn.close()
    return jsonify([dict(student) for student in students])


@app.route("/subjects")
@login_required
def subjects():
    conn = get_db_connection()
    try:
        subjects = conn.execute(
            """SELECT s.*, GROUP_CONCAT(gl.grade_number) as grades FROM subjects s 
               JOIN subject_grades sg ON s.id = sg.subject_id 
               JOIN grade_levels gl ON sg.grade_id = gl.id 
               GROUP BY s.id ORDER BY s.subject_name"""
        ).fetchall()
    except:
        # Fallback to old structure
        subjects = conn.execute(
            "SELECT * FROM subjects ORDER BY subject_name"
        ).fetchall()
    conn.close()
    return render_template("subjects.html", subjects=subjects)


@app.route("/add_subject", methods=["GET", "POST"])
@login_required
@role_required(["admin", "director"])
def add_subject():
    if request.method == "POST":
        conn = get_db_connection()
        subject_name = request.form["subject_name"]
        selected_grades = request.form.getlist("grades")
        
        if not selected_grades:
            flash("Please select at least one grade")
            return render_template("add_subject.html")
        
        # Generate unique subject_code
        base_code = subject_name.replace(" ", "").upper()[:8]
        subject_code = base_code
        counter = 1
        
        # Check for existing codes and add number if needed
        while conn.execute("SELECT id FROM subjects WHERE subject_code = ?", (subject_code,)).fetchone():
            subject_code = f"{base_code}{counter:02d}"
            counter += 1
        
        # Insert subject
        cursor = conn.execute(
            "INSERT INTO subjects (subject_code, subject_name) VALUES (?, ?)",
            (subject_code, subject_name),
        )
        subject_id = cursor.lastrowid
        
        # Insert subject-grade relationships
        for grade in selected_grades:
            grade_id = int(grade) - 8  # Convert grade 9->1, 10->2, etc.
            conn.execute(
                "INSERT OR IGNORE INTO subject_grades (subject_id, grade_id) VALUES (?, ?)",
                (subject_id, grade_id)
            )
        
        conn.commit()
        conn.close()
        flash(f"Subject added successfully with code: {subject_code}")
        return redirect(url_for("subjects"))
    return render_template("add_subject.html")


@app.route("/announcements")
@login_required
def announcements():
    conn = get_db_connection()
    announcements = conn.execute(
        """SELECT a.*, u.first_name, u.last_name FROM announcements a 
           LEFT JOIN users u ON a.created_by = u.id 
           WHERE a.target_audience IN (?, 'all') 
           ORDER BY a.created_at DESC""",
        (session["role"],),
    ).fetchall()
    conn.close()
    return render_template("announcements.html", announcements=announcements)


@app.route("/add_announcement", methods=["GET", "POST"])
@login_required
@role_required(["admin", "director", "teacher"])
def add_announcement():
    if request.method == "POST":
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO announcements (title, content, target_audience, created_by) VALUES (?, ?, ?, ?)",
            (
                request.form["title"],
                request.form["content"],
                request.form["target_audience"],
                session["user_id"],
            ),
        )
        conn.commit()
        conn.close()
        flash("Announcement posted successfully")
        return redirect(url_for("announcements"))
    return render_template("add_announcement.html")


@app.route("/school_info")
@login_required
@role_required(["admin", "director"])
def school_info():
    conn = get_db_connection()
    school = conn.execute("SELECT * FROM school_info LIMIT 1").fetchone()
    conn.close()
    return render_template("school_info.html", school=school)


@app.route("/edit_school_info", methods=["POST"])
@login_required
@role_required(["admin", "director"])
def edit_school_info():
    conn = get_db_connection()
    conn.execute(
        """UPDATE school_info SET school_name = ?, school_code = ?, address = ?, 
           phone = ?, email = ?, director_name = ? WHERE id = 1""",
        (
            request.form["school_name"],
            request.form["school_code"],
            request.form["address"],
            request.form["phone"],
            request.form["email"],
            request.form["director_name"],
        ),
    )
    conn.commit()
    conn.close()
    flash("School information updated successfully")
    return redirect(url_for("school_info"))


@app.route("/class_report/<int:class_id>")
@login_required
def class_report(class_id):
    conn = get_db_connection()
    class_info = conn.execute(
        """SELECT c.*, s.subject_name, u.first_name as teacher_first, u.last_name as teacher_last 
           FROM classes c 
           LEFT JOIN subjects s ON c.subject_id = s.id 
           LEFT JOIN teachers t ON c.teacher_id = t.id 
           LEFT JOIN users u ON t.user_id = u.id 
           WHERE c.id = ?""",
        (class_id,),
    ).fetchone()

    students = conn.execute(
        """SELECT s.*, u.first_name, u.last_name,
           AVG(CASE WHEN g.subject_id = ? THEN (g.score / g.max_score * 100) END) as avg_grade,
           COUNT(CASE WHEN a.status = 'present' THEN 1 END) as present_days,
           COUNT(a.id) as total_days
           FROM students s 
           LEFT JOIN users u ON s.user_id = u.id
           LEFT JOIN grades g ON s.id = g.student_id 
           LEFT JOIN attendance a ON s.id = a.student_id AND a.class_id = ?
           WHERE s.grade = ? AND s.section = ?
           GROUP BY s.id ORDER BY u.last_name""",
        (
            class_info["subject_id"],
            class_id,
            class_info["grade"],
            class_info["section"],
        ),
    ).fetchall()
    conn.close()
    return render_template(
        "class_report.html", class_info=class_info, students=students
    )


@app.route("/parent_portal")
@login_required
@role_required(["parent"])
def parent_portal():
    conn = get_db_connection()
    children = conn.execute(
        """SELECT s.* FROM students s 
           JOIN parent_student ps ON s.id = ps.student_id 
           WHERE ps.parent_id = ?""",
        (session["user_id"],),
    ).fetchall()
    conn.close()
    return render_template("parent_portal.html", children=children)


@app.route("/edit_student/<int:student_id>", methods=["GET", "POST"])
@login_required
@role_required(["admin", "director"])
def edit_student(student_id):
    conn = get_db_connection()
    if request.method == "POST":
        conn.execute(
            """UPDATE students SET grade = ?, section = ?, parent_phone = ?, address = ?, birth_date = ? WHERE id = ?""",
            (
                request.form["grade"],
                request.form["section"],
                request.form["parent_phone"],
                request.form["address"],
                request.form["birth_date"],
                student_id,
            ),
        )
        student_user = conn.execute("SELECT user_id FROM students WHERE id = ?", (student_id,)).fetchone()
        if student_user and student_user["user_id"]:
            conn.execute(
                "UPDATE users SET first_name = ?, last_name = ?, phone = ?, email = ? WHERE id = ?",
                (request.form["first_name"], request.form["last_name"], request.form.get("phone", ""), request.form.get("email", ""), student_user["user_id"])
            )
        conn.commit()
        conn.close()
        flash("Student updated successfully")
        return redirect(url_for("students"))

    student = conn.execute(
        """SELECT s.*, u.first_name, u.last_name FROM students s 
           LEFT JOIN users u ON s.user_id = u.id 
           WHERE s.id = ?""", (student_id,)
    ).fetchone()
    conn.close()
    return render_template("edit_student.html", student=student)


@app.route("/delete_student/<int:student_id>")
@login_required
@role_required(["admin", "director"])
def delete_student(student_id):
    conn = get_db_connection()
    student = conn.execute("SELECT user_id FROM students WHERE id = ?", (student_id,)).fetchone()
    conn.execute("DELETE FROM grades WHERE student_id = ?", (student_id,))
    conn.execute("DELETE FROM attendance WHERE student_id = ?", (student_id,))
    conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
    if student and student["user_id"]:
        conn.execute("DELETE FROM users WHERE id = ?", (student["user_id"],))
    conn.commit()
    conn.close()
    flash("Student deleted successfully")
    return redirect(url_for("students"))


@app.route("/edit_teacher/<int:teacher_id>", methods=["GET", "POST"])
@login_required
@role_required(["admin", "director"])
def edit_teacher(teacher_id):
    conn = get_db_connection()
    if request.method == "POST":
        conn.execute(
            """UPDATE teachers SET subject = ?, qualification = ?, hire_date = ? WHERE id = ?""",
            (
                request.form["subject"],
                request.form["qualification"],
                request.form["hire_date"],
                teacher_id,
            ),
        )
        conn.commit()
        conn.close()
        flash("Teacher updated successfully")
        return redirect(url_for("teachers"))

    teacher = conn.execute(
        """SELECT t.*, u.first_name, u.last_name FROM teachers t 
           LEFT JOIN users u ON t.user_id = u.id 
           WHERE t.id = ?""", (teacher_id,)
    ).fetchone()
    subjects = conn.execute("SELECT DISTINCT subject_name FROM subjects").fetchall()
    conn.close()
    return render_template("edit_teacher.html", teacher=teacher, subjects=subjects)


@app.route("/delete_teacher/<int:teacher_id>")
@login_required
@role_required(["admin", "director"])
def delete_teacher(teacher_id):
    conn = get_db_connection()
    teacher = conn.execute("SELECT user_id FROM teachers WHERE id = ?", (teacher_id,)).fetchone()
    conn.execute(
        "UPDATE classes SET teacher_id = NULL WHERE teacher_id = ?", (teacher_id,)
    )
    conn.execute("DELETE FROM teachers WHERE id = ?", (teacher_id,))
    if teacher and teacher["user_id"]:
        conn.execute("DELETE FROM users WHERE id = ?", (teacher["user_id"],))
    conn.commit()
    conn.close()
    flash("Teacher deleted successfully")
    return redirect(url_for("teachers"))


@app.route("/edit_class/<int:class_id>", methods=["GET", "POST"])
@login_required
@role_required(["admin", "director"])
def edit_class(class_id):
    conn = get_db_connection()
    if request.method == "POST":
        conn.execute(
            """UPDATE classes SET class_name = ?, grade = ?, section = ?, teacher_id = ?, 
               subject_id = ?, schedule = ? WHERE id = ?""",
            (
                request.form["class_name"],
                request.form["grade"],
                request.form["section"],
                request.form["teacher_id"] or None,
                request.form["subject_id"] or None,
                request.form["schedule"],
                class_id,
            ),
        )
        conn.commit()
        conn.close()
        flash("Class updated successfully")
        return redirect(url_for("classes"))

    class_info = conn.execute(
        "SELECT * FROM classes WHERE id = ?", (class_id,)
    ).fetchone()
    teachers = conn.execute(
        """SELECT t.*, u.first_name, u.last_name FROM teachers t 
           LEFT JOIN users u ON t.user_id = u.id 
           ORDER BY u.last_name"""
    ).fetchall()
    subjects = conn.execute("SELECT * FROM subjects ORDER BY subject_name").fetchall()
    conn.close()
    return render_template(
        "edit_class.html", class_info=class_info, teachers=teachers, subjects=subjects
    )


@app.route("/delete_class/<int:class_id>")
@login_required
@role_required(["admin", "director"])
def delete_class(class_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM attendance WHERE class_id = ?", (class_id,))
    conn.execute("DELETE FROM classes WHERE id = ?", (class_id,))
    conn.commit()
    conn.close()
    flash("Class deleted successfully")
    return redirect(url_for("classes"))


@app.route("/create_user_accounts")
@login_required
@role_required(["admin", "director"])
def create_user_accounts():
    conn = get_db_connection()

    # Create student accounts
    students = conn.execute("SELECT * FROM students").fetchall()
    for student in students:
        username = student["student_id"].lower()
        password = generate_password_hash("student123")
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)",
            (username, password, "student"),
        )
        # Link student to user account
        user = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if user:
            conn.execute(
                "UPDATE students SET id = ? WHERE id = ?", (user["id"], student["id"])
            )

    # Create teacher accounts
    teachers = conn.execute("SELECT * FROM teachers").fetchall()
    for teacher in teachers:
        username = teacher["teacher_id"].lower()
        password = generate_password_hash("teacher123")
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)",
            (username, password, "teacher"),
        )
        # Link teacher to user account
        user = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if user:
            conn.execute(
                "UPDATE teachers SET id = ? WHERE id = ?", (user["id"], teacher["id"])
            )

    conn.commit()
    conn.close()
    flash("User accounts created successfully")
    return redirect(url_for("index"))


@app.route("/my_classes")
@login_required
@role_required(["teacher"])
def my_classes():
    conn = get_db_connection()
    # Get teacher ID from teachers table
    teacher = conn.execute(
        "SELECT id FROM teachers WHERE user_id = ?", (session["user_id"],)
    ).fetchone()
    
    if teacher:
        classes = conn.execute(
            """SELECT c.*, s.subject_name FROM classes c 
               LEFT JOIN subjects s ON c.subject_id = s.id 
               WHERE c.teacher_id = ?""",
            (teacher["id"],),
        ).fetchall()
    else:
        classes = []
    
    conn.close()
    return render_template("my_classes.html", classes=classes)


@app.route("/my_students")
@login_required
@role_required(["teacher"])
def my_students():
    conn = get_db_connection()
    # Get teacher ID from teachers table
    teacher = conn.execute(
        "SELECT id FROM teachers WHERE user_id = ?", (session["user_id"],)
    ).fetchone()
    
    if teacher:
        students = conn.execute(
            """SELECT DISTINCT s.*, u.first_name, u.last_name FROM students s 
               LEFT JOIN users u ON s.user_id = u.id
               JOIN classes c ON s.grade = c.grade AND s.section = c.section 
               WHERE c.teacher_id = ? ORDER BY u.last_name""",
            (teacher["id"],),
        ).fetchall()
    else:
        students = []
    
    conn.close()
    return render_template("my_students.html", students=students)


@app.route("/grade_entry")
@login_required
@role_required(["teacher"])
def grade_entry():
    conn = get_db_connection()
    teacher = conn.execute(
        "SELECT id FROM teachers WHERE user_id = ?", (session["user_id"],)
    ).fetchone()
    
    if not teacher:
        flash("Teacher record not found")
        return redirect(url_for("index"))
    
    # Get teacher's subjects
    subjects = conn.execute(
        """SELECT DISTINCT s.* FROM subjects s 
           JOIN classes c ON s.id = c.subject_id 
           WHERE c.teacher_id = ?""",
        (teacher["id"],)
    ).fetchall()
    
    selected_subject = request.args.get('subject_id')
    students_data = []
    
    if selected_subject:
        # Get students for this subject
        students = conn.execute(
            """SELECT DISTINCT s.*, u.first_name, u.last_name FROM students s 
               LEFT JOIN users u ON s.user_id = u.id
               JOIN classes c ON s.grade = c.grade AND s.section = c.section 
               WHERE c.teacher_id = ? AND c.subject_id = ? ORDER BY u.last_name""",
            (teacher["id"], selected_subject)
        ).fetchall()
        
        # Get existing grades for each student
        for student in students:
            test1 = conn.execute(
                """SELECT score, max_score FROM grades 
                   WHERE student_id = ? AND subject_id = ? AND assessment_type = 'test' AND notes = 'Test 1'""",
                (student["id"], selected_subject)
            ).fetchone()
            
            test2 = conn.execute(
                """SELECT score, max_score FROM grades 
                   WHERE student_id = ? AND subject_id = ? AND assessment_type = 'test' AND notes = 'Test 2'""",
                (student["id"], selected_subject)
            ).fetchone()
            
            assignment = conn.execute(
                """SELECT AVG(score) as score, AVG(max_score) as max_score FROM grades 
                   WHERE student_id = ? AND subject_id = ? AND assessment_type = 'assignment'""",
                (student["id"], selected_subject)
            ).fetchone()
            
            final = conn.execute(
                """SELECT score, max_score FROM grades 
                   WHERE student_id = ? AND subject_id = ? AND assessment_type = 'final'
                   ORDER BY date_recorded DESC LIMIT 1""",
                (student["id"], selected_subject)
            ).fetchone()
            
            students_data.append({
                'student': student,
                'test1': test1,
                'test2': test2,
                'assignment': assignment,
                'final': final
            })
    
    conn.close()
    return render_template("grade_entry.html", subjects=subjects, students_data=students_data, selected_subject=selected_subject)


@app.route("/save_grades", methods=["POST"])
@login_required
@role_required(["teacher"])
def save_grades():
    conn = get_db_connection()
    subject_id = request.form["subject_id"]
    
    for key, value in request.form.items():
        if key.startswith("grade_"):
            parts = key.split("_")
            student_id = parts[1]
            assessment_name = parts[2]
            
            # Map assessment names to valid types
            assessment_mapping = {
                'test1': 'test',
                'test2': 'test', 
                'assignment': 'assignment',
                'final': 'final'
            }
            
            assessment_type = assessment_mapping.get(assessment_name)
            
            if value and assessment_type:
                # Validate grade value
                try:
                    grade_value = float(value)
                    if grade_value < 0 or grade_value > 100:
                        flash(f"Invalid grade {grade_value} for student {student_id}. Grades must be between 0 and 100.")
                        continue
                except ValueError:
                    flash(f"Invalid grade value for student {student_id}")
                    continue
                
                # Handle test1 and test2 as independent exams
                if assessment_name == 'test1':
                    # Delete existing test1 grade
                    conn.execute(
                        "DELETE FROM grades WHERE student_id = ? AND subject_id = ? AND assessment_type = 'test' AND (notes = 'Test 1' OR notes IS NULL)",
                        (student_id, subject_id)
                    )
                    # Insert new test1 grade
                    conn.execute(
                        "INSERT INTO grades (student_id, subject_id, assessment_type, score, max_score, notes) VALUES (?, ?, ?, ?, ?, 'Test 1')",
                        (student_id, subject_id, assessment_type, grade_value, 100)
                    )
                elif assessment_name == 'test2':
                    # Delete existing test2 grade
                    conn.execute(
                        "DELETE FROM grades WHERE student_id = ? AND subject_id = ? AND assessment_type = 'test' AND notes = 'Test 2'",
                        (student_id, subject_id)
                    )
                    # Insert new test2 grade
                    conn.execute(
                        "INSERT INTO grades (student_id, subject_id, assessment_type, score, max_score, notes) VALUES (?, ?, ?, ?, ?, 'Test 2')",
                        (student_id, subject_id, assessment_type, grade_value, 100)
                    )
                else:
                    # Delete existing grade for assignment/final
                    conn.execute(
                        "DELETE FROM grades WHERE student_id = ? AND subject_id = ? AND assessment_type = ?",
                        (student_id, subject_id, assessment_type)
                    )
                    # Insert new grade
                    conn.execute(
                        "INSERT INTO grades (student_id, subject_id, assessment_type, score, max_score) VALUES (?, ?, ?, ?, ?)",
                        (student_id, subject_id, assessment_type, grade_value, 100)
                    )
    
    conn.commit()
    conn.close()
    flash("Grades saved successfully")
    return redirect(url_for("grade_entry", subject_id=subject_id))


@app.route("/edit_profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    conn = get_db_connection()

    if request.method == "POST":
        # Update users table for all roles
        conn.execute(
            "UPDATE users SET first_name = ?, last_name = ?, phone = ?, email = ? WHERE id = ?",
            (
                request.form.get("first_name", ""),
                request.form.get("last_name", ""),
                request.form.get("phone", ""),
                request.form.get("email", ""),
                session["user_id"],
            ),
        )
        
        # Update role-specific tables if needed
        if session["role"] == "student":
            conn.execute(
                "UPDATE students SET address = ? WHERE user_id = ?",
                (request.form.get("address", ""), session["user_id"]),
            )

        conn.commit()
        conn.close()
        flash("Profile updated successfully")
        return redirect(url_for("profile"))

    if session["role"] == "student":
        user_data = conn.execute(
            """SELECT u.*, s.address, s.grade, s.section FROM users u 
               LEFT JOIN students s ON u.id = s.user_id 
               WHERE u.id = ?""", (session["user_id"],)
        ).fetchone()
    elif session["role"] == "teacher":
        user_data = conn.execute(
            """SELECT u.*, t.subject, t.qualification FROM users u 
               LEFT JOIN teachers t ON u.id = t.user_id 
               WHERE u.id = ?""", (session["user_id"],)
        ).fetchone()
    else:
        user_data = conn.execute(
            "SELECT * FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()

    conn.close()
    return render_template("edit_profile.html", user_data=user_data)


@app.route("/force_change_password", methods=["GET", "POST"])
@login_required
def force_change_password():
    if request.method == "POST":
        new_password = request.form["new_password"]
        confirm_password = request.form["confirm_password"]

        if new_password != confirm_password:
            flash("Passwords do not match")
        elif len(new_password) < 6:
            flash("Password must be at least 6 characters long")
        elif new_password == "Temp2024!":
            flash("Please choose a different password from the temporary one")
        else:
            conn = get_db_connection()
            hashed_password = generate_password_hash(new_password)
            conn.execute(
                "UPDATE users SET password = ? WHERE id = ?",
                (hashed_password, session["user_id"]),
            )
            conn.commit()
            conn.close()
            session.pop("must_change_password", None)
            flash("Password changed successfully! Welcome to e-Lemis.")
            return redirect(url_for("index"))

    return render_template("force_change_password.html")


@app.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_password = request.form["current_password"]
        new_password = request.form["new_password"]
        confirm_password = request.form["confirm_password"]

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", (session["username"],)
        ).fetchone()

        if not check_password_hash(user["password"], current_password):
            flash("Current password is incorrect")
        elif new_password != confirm_password:
            flash("New passwords do not match")
        elif len(new_password) < 6:
            flash("Password must be at least 6 characters long")
        else:
            hashed_password = generate_password_hash(new_password)
            conn.execute(
                "UPDATE users SET password = ? WHERE id = ?",
                (hashed_password, session["user_id"]),
            )
            conn.commit()
            flash("Password changed successfully")
            conn.close()
            return redirect(url_for("profile"))

        conn.close()

    return render_template("change_password.html")


@app.route("/academic_years")
@login_required
@role_required(["admin", "director"])
def academic_years():
    conn = get_db_connection()
    years = conn.execute(
        "SELECT * FROM academic_years ORDER BY start_date DESC"
    ).fetchall()
    conn.close()
    return render_template("academic_years.html", years=years)


@app.route("/add_academic_year", methods=["GET", "POST"])
@login_required
@role_required(["admin", "director"])
def add_academic_year():
    if request.method == "POST":
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO academic_years (year_name, ethiopian_year, gregorian_year, start_date, end_date) VALUES (?, ?, ?, ?, ?)",
            (
                request.form["year_name"],
                request.form["ethiopian_year"],
                request.form["gregorian_year"],
                request.form["start_date"],
                request.form["end_date"],
            ),
        )
        conn.commit()
        conn.close()
        flash("Academic year added successfully")
        return redirect(url_for("academic_years"))
    return render_template("add_academic_year.html")


@app.route("/activate_year/<int:year_id>")
@login_required
@role_required(["admin", "director"])
def activate_year(year_id):
    conn = get_db_connection()
    conn.execute("UPDATE academic_years SET is_active = 0")
    conn.execute("UPDATE academic_years SET is_active = 1 WHERE id = ?", (year_id,))
    conn.commit()
    conn.close()
    flash("Academic year activated successfully")
    return redirect(url_for("academic_years"))


@app.route("/bulk_register", methods=["GET", "POST"])
@login_required
@role_required(["admin", "director"])
def bulk_register():
    if request.method == "POST":
        if 'csv_file' not in request.files:
            flash("No file uploaded")
            return redirect(url_for('bulk_register'))
            
        file = request.files['csv_file']
        if file.filename == '':
            flash("No file selected")
            return redirect(url_for('bulk_register'))
            
        if not file.filename.endswith('.csv'):
            flash("Invalid file format. Please upload a CSV file.")
            return redirect(url_for('bulk_register'))
            
        grade = request.form.get('grade')
        if not grade:
            flash("Please select a grade.")
            return redirect(url_for('bulk_register'))
            
        import csv
        import io
        
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.DictReader(stream)
        
        conn = get_db_connection()
        role = conn.execute('SELECT id FROM roles WHERE role_name = "student"').fetchone()
        
        success_count = 0
        error_count = 0
        
        # Get starting max_id
        max_id_row = conn.execute('SELECT MAX(id) as max_id FROM students').fetchone()
        current_max_id = max_id_row['max_id'] if max_id_row and max_id_row['max_id'] else 0
        
        try:
            for row in csv_input:
                first_name = row.get("First Name", "").strip()
                last_name = row.get("Last Name", "").strip()
                section = row.get("Section", "").strip()
                parent_phone = row.get("Parent Phone", "").strip()
                address = row.get("Address", "").strip()
                birth_date = row.get("Birth Date", "").strip()
                
                if not first_name or not last_name:
                    error_count += 1
                    continue
                    
                current_max_id += 1
                student_id = f"STU-{current_max_id:07d}"
                
                cursor = conn.execute(
                    "INSERT INTO users (first_name, last_name, username, password, status) VALUES (?, ?, ?, ?, ?)",
                    (first_name, last_name, student_id.lower(), generate_password_hash("Temp2024!"), "active"),
                )
                user_id = cursor.lastrowid
                
                conn.execute(
                    "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
                    (user_id, role["id"]),
                )
                
                conn.execute(
                    "INSERT INTO students (user_id, student_id, grade, section, parent_phone, address, birth_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, student_id, grade, section, parent_phone, address, birth_date),
                )
                success_count += 1
                
            conn.commit()
            flash(f"Bulk registration completed! {success_count} added, {error_count} skipped.")
        except Exception as e:
            conn.rollback()
            flash(f"Error processing CSV: {str(e)}")
        finally:
            conn.close()
            
        return redirect(url_for("students"))
        
    return render_template("bulk_register.html")

@app.route("/download_template_student_csv")
@login_required
@role_required(["admin", "director"])
def download_template_student_csv():
    import io
    import csv
    from flask import Response
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["First Name", "Last Name", "Section", "Parent Phone", "Address", "Birth Date"])
    writer.writerow(["John", "Doe", "A", "0911223344", "Addis Ababa", "2005-05-15"])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=student_template.csv"}
    )


@app.route("/promote_students", methods=["GET", "POST"])
@login_required
@role_required(["admin", "director"])
def promote_students():
    if request.method == "POST":
        from_grade = request.form["from_grade"]
        to_grade = request.form["to_grade"]

        conn = get_db_connection()
        conn.execute(
            'UPDATE students SET grade = ? WHERE grade = ? AND status = "active"',
            (to_grade, from_grade),
        )
        conn.commit()
        conn.close()
        flash(f"Students promoted from Grade {from_grade} to Grade {to_grade}")
        return redirect(url_for("students"))
    return render_template("promote_students.html")


@app.route("/messages")
@login_required
def messages():
    conn = get_db_connection()
    messages = conn.execute(
        """SELECT m.*, u.first_name, u.last_name FROM messages m 
           JOIN users u ON m.sender_id = u.id 
           WHERE m.recipient_id = ? ORDER BY m.sent_at DESC""",
        (session["user_id"],),
    ).fetchall()
    conn.close()
    return render_template("messages.html", messages=messages)


@app.route("/send_message", methods=["GET", "POST"])
@login_required
def send_message():
    if request.method == "POST":
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO messages (sender_id, recipient_id, subject, content) VALUES (?, ?, ?, ?)",
            (
                session["user_id"],
                request.form["recipient_id"],
                request.form["subject"],
                request.form["content"],
            ),
        )
        conn.commit()
        conn.close()
        flash("Message sent successfully")
        return redirect(url_for("messages"))

    conn = get_db_connection()
    if session["role"] == "parent":
        recipients = conn.execute(
            """SELECT DISTINCT u.id, u.first_name, u.last_name FROM users u 
               JOIN teachers t ON u.id = t.id 
               JOIN classes c ON t.id = c.teacher_id 
               JOIN students s ON s.grade = c.grade AND s.section = c.section 
               JOIN parent_student ps ON s.id = ps.student_id 
               WHERE ps.parent_id = ?""",
            (session["user_id"],),
        ).fetchall()
    elif session["role"] == "teacher":
        recipients = conn.execute(
            """SELECT DISTINCT u.id, u.first_name, u.last_name FROM users u 
               JOIN user_roles ur ON u.id = ur.user_id 
               JOIN roles r ON ur.role_id = r.id 
               WHERE r.role_name IN ('parent', 'admin', 'director')"""
        ).fetchall()
    else:
        recipients = conn.execute(
            """SELECT u.id, u.first_name, u.last_name FROM users u 
               JOIN user_roles ur ON u.id = ur.user_id 
               JOIN roles r ON ur.role_id = r.id 
               WHERE r.role_name != ?""",
            (session["role"],),
        ).fetchall()

    conn.close()
    return render_template("send_message.html", recipients=recipients)


@app.route("/resources")
@login_required
def resources():
    conn = get_db_connection()
    if session["role"] == "student":
        student = conn.execute(
            "SELECT grade FROM students WHERE id = ?", (session["user_id"],)
        ).fetchone()
        resources = conn.execute(
            """SELECT r.*, s.subject_name FROM resources r 
               LEFT JOIN subjects s ON r.subject_id = s.id 
               WHERE r.grade = ? OR r.grade IS NULL""",
            (student["grade"],),
        ).fetchall()
    else:
        resources = conn.execute(
            """SELECT r.*, s.subject_name FROM resources r 
               LEFT JOIN subjects s ON r.subject_id = s.id"""
        ).fetchall()
    conn.close()
    return render_template("resources.html", resources=resources)


@app.route("/upload_resource", methods=["GET", "POST"])
@login_required
@role_required(["admin", "director", "teacher"])
def upload_resource():
    if request.method == "POST":
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO resources (title, description, subject_id, grade, uploaded_by) VALUES (?, ?, ?, ?, ?)",
            (
                request.form["title"],
                request.form["description"],
                request.form["subject_id"] or None,
                request.form["grade"] or None,
                session["user_id"],
            ),
        )
        conn.commit()
        conn.close()
        flash("Resource uploaded successfully")
        return redirect(url_for("resources"))

    conn = get_db_connection()
    subjects = conn.execute("SELECT * FROM subjects ORDER BY subject_name").fetchall()
    conn.close()
    return render_template("upload_resource.html", subjects=subjects)


@app.route("/transcripts")
@login_required
@role_required(["admin", "director"])
def transcripts():
    conn = get_db_connection()
    grade12_students = conn.execute(
        """SELECT s.*, u.first_name, u.last_name FROM students s 
           LEFT JOIN users u ON s.user_id = u.id 
           WHERE s.grade = 12 ORDER BY u.last_name"""
    ).fetchall()
    conn.close()
    return render_template("transcripts.html", students=grade12_students)


@app.route("/transcript/<int:student_id>")
@login_required
def transcript(student_id):
    conn = get_db_connection()
    student = conn.execute(
        """SELECT s.*, u.first_name, u.last_name FROM students s 
           LEFT JOIN users u ON s.user_id = u.id 
           WHERE s.id = ?""",
        (student_id,),
    ).fetchone()
    grades = conn.execute(
        """SELECT g.*, s.subject_name, s.grade as subject_grade FROM grades g 
           JOIN subjects s ON g.subject_id = s.id 
           WHERE g.student_id = ? ORDER BY s.grade, s.subject_name""",
        (student_id,),
    ).fetchall()
    conn.close()
    from datetime import date

    return render_template(
        "transcript.html", student=student, grades=grades, today=date.today()
    )


@app.route("/eslce_forms")
@login_required
@role_required(["admin", "director"])
def eslce_forms():
    conn = get_db_connection()
    grade12_students = conn.execute(
        """SELECT s.*, u.first_name, u.last_name FROM students s 
           LEFT JOIN users u ON s.user_id = u.id 
           WHERE s.grade = 12 AND s.status = "active" ORDER BY u.last_name"""
    ).fetchall()
    conn.close()
    return render_template("eslce_forms.html", students=grade12_students)


@app.route("/academic_performance/<int:student_id>")
@login_required
def academic_performance(student_id):
    conn = get_db_connection()
    
    if session.get("role") == "student":
        student_check = conn.execute("SELECT id FROM students WHERE user_id = ?", (session["user_id"],)).fetchone()
        if not student_check or student_check["id"] != student_id:
            flash("Access denied: You can only view your own academic performance.")
            return redirect(url_for("index"))
    
    # Check access permissions
    if session["role"] == "teacher":
        teacher = conn.execute(
            "SELECT id FROM teachers WHERE user_id = ?", (session["user_id"],)
        ).fetchone()
        if teacher:
            access_check = conn.execute(
                """SELECT 1 FROM students s 
                   JOIN classes c ON s.grade = c.grade AND s.section = c.section 
                   WHERE s.id = ? AND c.teacher_id = ?""",
                (student_id, teacher["id"])
            ).fetchone()
            if not access_check:
                flash("Access denied")
                return redirect(url_for("my_students"))
    
    # Get student info
    student = conn.execute(
        """SELECT s.*, u.first_name, u.last_name FROM students s 
           LEFT JOIN users u ON s.user_id = u.id 
           WHERE s.id = ?""", (student_id,)
    ).fetchone()
    
    if not student:
        flash("Student not found")
        return redirect(url_for("students"))
    
    # Get all subjects for the student's grade
    try:
        subjects = conn.execute(
            """SELECT s.* FROM subjects s 
               JOIN subject_grades sg ON s.id = sg.subject_id 
               JOIN grade_levels gl ON sg.grade_id = gl.id 
               WHERE gl.grade_number = ? ORDER BY s.subject_name""",
            (student["grade"],)
        ).fetchall()
    except:
        # Fallback to old structure
        subjects = conn.execute(
            "SELECT * FROM subjects WHERE grade = ? ORDER BY subject_name",
            (student["grade"],)
        ).fetchall()
    
    # Get grades organized by subject and assessment type
    performance_data = []
    total_average = 0
    subject_count = 0
    
    for subject in subjects:
        # Get grades for each assessment type
        test1 = conn.execute(
            """SELECT AVG(score/max_score*100) as avg FROM grades 
               WHERE student_id = ? AND subject_id = ? AND assessment_type = 'test' AND notes = 'Test 1'""",
            (student_id, subject["id"])
        ).fetchone()["avg"] or 0
        
        test2 = conn.execute(
            """SELECT AVG(score/max_score*100) as avg FROM grades 
               WHERE student_id = ? AND subject_id = ? AND assessment_type = 'test' AND notes = 'Test 2'""",
            (student_id, subject["id"])
        ).fetchone()["avg"] or 0
        
        assignment = conn.execute(
            """SELECT AVG(score/max_score*100) as avg FROM grades 
               WHERE student_id = ? AND subject_id = ? AND assessment_type = 'assignment'""",
            (student_id, subject["id"])
        ).fetchone()["avg"] or 0
        
        final = conn.execute(
            """SELECT AVG(score/max_score*100) as avg FROM grades 
               WHERE student_id = ? AND subject_id = ? AND assessment_type = 'final'""",
            (student_id, subject["id"])
        ).fetchone()["avg"] or 0
        
        # Calculate total for this subject (weighted average)
        subject_total = (test1 * 0.2) + (test2 * 0.2) + (assignment * 0.2) + (final * 0.4)
        
        performance_data.append({
            'subject': subject["subject_name"],
            'test1': round(test1, 1),
            'test2': round(test2, 1),
            'assignment': round(assignment, 1),
            'final': round(final, 1),
            'total': round(subject_total, 1)
        })
        
        if subject_total > 0:
            total_average += subject_total
            subject_count += 1
    
    # Calculate overall average
    overall_average = round(total_average / subject_count, 1) if subject_count > 0 else 0
    
    # Get class ranking
    class_students = conn.execute(
        """SELECT s.id FROM students s 
           WHERE s.grade = ? AND s.section = ? AND s.status = 'active'""",
        (student["grade"], student["section"])
    ).fetchall()
    
    # Calculate averages for all students in class for ranking
    student_averages = []
    for class_student in class_students:
        student_total = 0
        student_subject_count = 0
        
        for subject in subjects:
            test1_avg = conn.execute(
                """SELECT AVG(score/max_score*100) as avg FROM grades 
                   WHERE student_id = ? AND subject_id = ? AND assessment_type = 'test'""",
                (class_student["id"], subject["id"])
            ).fetchone()["avg"] or 0
            
            assignment_avg = conn.execute(
                """SELECT AVG(score/max_score*100) as avg FROM grades 
                   WHERE student_id = ? AND subject_id = ? AND assessment_type = 'assignment'""",
                (class_student["id"], subject["id"])
            ).fetchone()["avg"] or 0
            
            final_avg = conn.execute(
                """SELECT AVG(score/max_score*100) as avg FROM grades 
                   WHERE student_id = ? AND subject_id = ? AND assessment_type = 'final'""",
                (class_student["id"], subject["id"])
            ).fetchone()["avg"] or 0
            
            subject_avg = (test1_avg * 0.4) + (assignment_avg * 0.2) + (final_avg * 0.4)
            if subject_avg > 0:
                student_total += subject_avg
                student_subject_count += 1
        
        student_overall = student_total / student_subject_count if student_subject_count > 0 else 0
        student_averages.append((class_student["id"], student_overall))
    
    # Sort by average (descending) and find rank
    student_averages.sort(key=lambda x: x[1], reverse=True)
    rank = next((i + 1 for i, (sid, _) in enumerate(student_averages) if sid == student_id), 0)
    total_students = len(student_averages)
    
    conn.close()
    
    return render_template(
        "academic_performance.html",
        student=student,
        performance_data=performance_data,
        overall_average=overall_average,
        rank=rank,
        total_students=total_students
    )


@app.route("/manage_accounts")
@login_required
@role_required(["admin", "director"])
def manage_accounts():
    conn = get_db_connection()
    users = conn.execute(
        """SELECT u.*, r.role_name FROM users u 
           LEFT JOIN user_roles ur ON u.id = ur.user_id 
           LEFT JOIN roles r ON ur.role_id = r.id 
           ORDER BY r.role_name, u.last_name"""
    ).fetchall()
    conn.close()
    return render_template("manage_accounts.html", users=users)


@app.route("/approve_account/<int:user_id>")
@login_required
@role_required(["admin", "director"])
def approve_account(user_id):
    conn = get_db_connection()
    conn.execute('UPDATE users SET status = "active" WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    flash("Account approved successfully")
    return redirect(url_for("manage_accounts"))


@app.route("/delete_account/<int:user_id>")
@login_required
@role_required(["admin", "director"])
def delete_account(user_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    flash("Account deleted successfully")
    return redirect(url_for("manage_accounts"))


@app.route("/deactivate_account/<int:user_id>")
@login_required
@role_required(["admin", "director"])
def deactivate_account(user_id):
    conn = get_db_connection()
    conn.execute('UPDATE users SET status = "inactive" WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    flash("Account deactivated successfully")
    return redirect(url_for("manage_accounts"))

@app.route("/activate_account/<int:user_id>")
@login_required
@role_required(["admin", "director"])
def activate_account(user_id):
    conn = get_db_connection()
    conn.execute('UPDATE users SET status = "active" WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    flash("Account activated successfully")
    return redirect(url_for("manage_accounts"))


@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        username = request.form["username"]
        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        if user:
            # In a real application, you would send an email with reset link
            # For now, we'll just show a message
            flash(
                "Password reset instructions have been sent to your registered email."
            )
        else:
            flash("Username not found.")

        conn.close()
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


# Session timeout (30 minutes)
@app.before_request
def check_session_timeout():
    if "user_id" in session:
        # Check if user must change password
        if session.get("must_change_password") and request.endpoint not in ["force_change_password", "logout"]:
            return redirect(url_for("force_change_password"))
            
        from datetime import datetime, timedelta

        last_activity = session.get("last_activity")
        if last_activity:
            if datetime.now() - datetime.fromisoformat(last_activity) > timedelta(
                minutes=30
            ):
                session.clear()
                flash("Session expired. Please log in again.")
                return redirect(url_for("login"))
        session["last_activity"] = datetime.now().isoformat()


@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404


@app.errorhandler(500)
def internal_error(error):
    return render_template("500.html"), 500


if __name__ == "__main__":
    if not os.path.exists(DATABASE):
        init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
