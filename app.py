from flask import Flask, render_template, request, redirect, url_for, send_file, jsonify, session, g
import threading
import time
import random
import qrcode
import io
import base64
import sqlite3

app = Flask(__name__)
app.config['DATABASE'] = 'students.db'
app.secret_key = '6NWMu7ewCqm7GX6tbG0hOJmU8QNWZ2A5'

# Initialize attendance_status
attendance_status = {'qr_data': '', 'qr_image': ''}
 



def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(app.config['DATABASE'])
        db.row_factory = sqlite3.Row
    return db


def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()


def close_db(e=None):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    result = cur.fetchall()
    cur.close()
    column_names = [column[0] for column in cur.description]

    if not result:
        return None

    if one:
        return dict(zip(column_names, result[0]))

    return [dict(zip(column_names, row)) for row in result]


# Function to generate a unique 6-digit key
def generate_unique_key():
    key = ''.join([str(random.randint(0, 9)) for _ in range(6)])
    return key

# Function to generate a unique session ID
# def generate_unique_session_id():
#     session_id = ''.join([str(random.randint(0, 9)) for _ in range(6)])
#     return session_id


# Function to generate a QR code
def generate_qr_code(qr_data):
    img = qrcode.make(qr_data)
    img_buffer = io.BytesIO()
    img.save(img_buffer)
    img_str = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
    return img_str


# Function to generate a QR code based on teacher input
def generate_qr_code_from_input(subject_name, time_slot, date):
    key = generate_unique_key()

    # Insert the key into the QR_key table
    db = get_db()
    db.execute('INSERT INTO QR_key (key_field, teacher_id) VALUES (?, ?)', (key, session['teacher_id']))
    db.commit()

    teacher_id = session['teacher_id'] 

    qr_data = f"{subject_name}_{time_slot}_{date}_{key}_{teacher_id}"

    img_str = generate_qr_code(qr_data)

    if subject_name == "CS" or subject_name == "CC":
        students = query_db('SELECT roll_no, name FROM students WHERE elective = ?', (subject_name,))
        if students is not None:
            db = get_db()
            for student in students:
                db.execute('INSERT INTO Temp_attendance (rollno, stdname, subject, date, time, attendance, teacher_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (student['roll_no'], student['name'], subject_name, date, time_slot, 0, teacher_id))
            db.commit()

    else:
        students = query_db('SELECT roll_no, name FROM students')
        db = get_db()
        for student in students:
            db.execute('INSERT INTO Temp_attendance (rollno, stdname, subject, date, time, attendance, teacher_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (student['roll_no'], student['name'], subject_name, date, time_slot, 0, session['teacher_id']))

        db.commit()

    # Update attendance_status with subject name, time slot, date, key, and session ID
    with threading.Lock():
        attendance_status['qr_data'] = qr_data
        attendance_status['subject_name'] = subject_name
        attendance_status['time_slot'] = time_slot
        attendance_status['date'] = date
        attendance_status['key'] = key
        attendance_status['teacher_id'] = teacher_id
        attendance_status['qr_image'] = img_str

    return {'qr_data': qr_data, 'qr_image': img_str}



# Initialize the database
with app.app_context():
    init_db()

# Route to display the QR code on the webpage
@app.route('/')
def home():
    return render_template('home.html')


@app.route('/generate_qr_code')
def generate_qrcode():
    # Trigger the generation of a new QR code when this route is accessed
    key = generate_unique_key()
    with app.app_context():
        qr_data = f"{attendance_status.get('subject_name', 'Unknown')}_{attendance_status.get('time_slot', 'Unknown')}_{attendance_status.get('date', 'Unknown')}_{key}_{attendance_status.get('teacher_id', 'Unknown')}"
        img_str = generate_qr_code(qr_data)

        teacher_id = attendance_status['teacher_id']

        # Update attendance_status
        attendance_status['qr_data'] = qr_data
        attendance_status['key'] = key
        attendance_status['qr_image'] = img_str

        # Insert the key into the QR_key table
        db = get_db()
        db.execute('INSERT INTO QR_key (key_field, teacher_id) VALUES (?, ?)', (key, teacher_id))
        db.commit()

    return "QR code generated successfully"

# Route to serve the QR code image
@app.route('/qr_image')
def qr_image():
    return send_file(io.BytesIO(base64.b64decode(attendance_status['qr_image'])), mimetype='image/png')


# Route to display the input page for the teacher
@app.route('/input', methods=['GET', 'POST'])
def input():
    if request.method == 'POST':
        subject_name = request.form['subject_name']
        time_slot = request.form['time_slot']
        date = request.form['date']
        result = generate_qr_code_from_input(subject_name, time_slot, date)
        return render_template('index.html', qr_data=result['qr_data'], qr_image=result['qr_image'])
    return render_template('input.html')


@app.route('/admin_profile')
def admin_profile():
    admin_username = session.get('admin_username')
    admin_dept = session.get('admin_dept')
    admin_class = session.get('admin_class')
    return jsonify({'admin_username': admin_username, 'admin_dept': admin_dept, 'admin_class': admin_class})


# Route to display the login page for students
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        roll_no = request.form['roll_no']
        password = request.form['password']

        user = query_db('SELECT * FROM students WHERE roll_no = ?', (roll_no,), one=True)

        # Check if the user exists and the password is correct
        if user and user['password'] == password:
            # Create a session for the logged-in student
            session['roll_no'] = user['roll_no']
            session['name'] = user['name']

            # Redirect to the QR scanner page after successful login
            return redirect(url_for('qr_scanner'))

        # Incorrect roll number or password
        return render_template('login.html', error='Invalid roll number or password')

    return render_template('login.html')

@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Check if the user is an admin
        admin = query_db('SELECT * FROM Admins WHERE Username = ? AND Password = ?', (username, password), one=True)
        if admin:
            # Create a session for the logged-in admin
            session['admin_username'] = admin['Username']
            session['admin_dept'] = admin['Dept']
            session['admin_class'] = admin['Class']
            session['teacher_id'] = admin['teacher_id']

            # Redirect to the admin options page after successful login
            return redirect(url_for('admin_options'))

        # Incorrect username or password
        return render_template('admin_login.html', error='Invalid username or password')

    return render_template('admin_login.html')

# Route for admin options page
@app.route('/admin_options')
def admin_options():
    # Check if the user is logged in as an admin
    if 'admin_username' not in session:
        # Redirect to the admin login page if not logged in
        return redirect(url_for('admin_login'))

    return render_template('admin_options.html')



@app.route('/qr_scanner')
def qr_scanner():
    # Check if the user is logged in
    if 'roll_no' not in session:
        # Redirect to the login page if not logged in
        return redirect(url_for('login'))

    # User is logged in, render the QR scanner page
    return render_template('qr_scanner.html')


# Route to process the detected QR code on the server
@app.route('/process_qr_code', methods=['POST'])
def process_qr_code():
    data = request.get_json()
    qr_code = data.get('qr_code')

    # Process the QR code and extract information
    qr_parts = qr_code.split('_')

    if len(qr_parts) == 5:
        subject_name, time_slot, date, key, teacher_id = qr_parts

        # Verify the key against the last generated key in QR_key for the specific session
        last_generated_key = query_db('SELECT key_field FROM QR_key WHERE teacher_id = ? ORDER BY id DESC LIMIT 1', (teacher_id,), one=True)

        if last_generated_key and key == last_generated_key['key_field']:
            # Key is valid, update attendance in Temp_attendance for the logged-in student
            roll_no = session.get('roll_no')
            db = get_db()
            db.execute('UPDATE Temp_attendance SET attendance = 1 WHERE rollno = ? AND subject = ? AND date = ? AND time = ? AND teacher_id = ?',
                       (roll_no, subject_name, date, time_slot, teacher_id))
            db.commit()

            # Respond with a success message
            return jsonify({'message': 'QR code processed successfully'})

    # Invalid QR code format, key, or session ID
    return jsonify({'error': 'Invalid QR code format, key, or session ID'})


@app.route('/admin_dashboard', methods=['POST', 'GET'])
def admin_dashboard():
    # Check if the user is logged in as an admin
    if 'admin_username' not in session:
        # Redirect to the admin login page if not logged in
        return redirect(url_for('admin_login'))

    no_records_found = False

    if request.method == 'POST':
        # If it's a POST request, retrieve form data
        subject_name = request.form['subject_name']
        time_slot = request.form['time_slot']
        date = request.form['date']

        # Run a query to fetch relevant records based on selected criteria
        records = query_db('SELECT * FROM Temp_attendance WHERE subject = ? AND time = ? AND date = ?',
                           (subject_name, time_slot, date))

        if not records:
            # No records found, set the flag
            no_records_found = True

        # Render the admin_dashboard template with the fetched records or no records message
        return render_template('admin_dashboard.html', records=records, no_records_found=no_records_found)

    # Admin is logged in, render the admin dashboard page (GET request)
    return render_template('admin_dashboard.html')



@app.route('/update_attendance', methods=['POST'])
def update_attendance():
    if 'admin_username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    rollno = data.get('rollno')
    subject = data.get('subject')
    date = data.get('date')
    time = data.get('time')
    attendance = int(data.get('attendance'))  # Convert attendance to an integer

    db = get_db()
    db.execute('UPDATE Temp_attendance SET attendance = ? WHERE rollno = ? AND subject = ? AND date = ? AND time = ?',
               (1 - attendance, rollno, subject, date, time))
    db.commit()

    return jsonify({'message': 'Attendance updated successfully'})  

from flask import jsonify

@app.route('/attendance_summary', methods=['POST'])
def attendance_summary():
    # Check if the user is logged in as an admin
    if 'admin_username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.form
    date = data.get('date')

    # Specify the subjects you want to include in the summary
    subjects = ['WAD', 'DSBDA', 'CC', 'CS', 'CNS']

    # Initialize subject_counts dictionary to store attendance summary and time slots
    subject_counts = {}

    # Fetch attendance summary and time slot for each subject
    for subject in subjects:
        # Fetch time slot from Temp_attendance for the given subject and date
        time_slot_result = query_db('SELECT time FROM Temp_attendance WHERE subject = ? AND date = ? LIMIT 1', (subject, date))

        # Fetch attendance summary for the subject
        summary = query_db('SELECT attendance, COUNT(*) as count FROM Temp_attendance WHERE subject = ? AND date = ? GROUP BY attendance', (subject, date))

        # Process the summary data for the subject
        for row in summary:
            if subject not in subject_counts:
                subject_counts[subject] = {
                    'present_count': 0,
                    'absent_count': 0,
                    'time_slot': time_slot_result[0]['time'] if time_slot_result else 'N/A'
                }

            if row['attendance'] == 1:
                subject_counts[subject]['present_count'] = row['count']
            elif row['attendance'] == 0:
                subject_counts[subject]['absent_count'] = row['count']

    return jsonify(subject_counts)




@app.route('/studentcnt')
def studentcnt():
    return render_template('studentcnt.html ')



@app.route('/profile')
def profile():
    name = session.get('name')
    roll_no = session.get('roll_no')
    return jsonify({'username': name, 'roll_no': roll_no})


# Route to logout and end the session
@app.route('/logout')
def logout():
    session.clear()
    return jsonify({'message': 'Logged out successfully'})

@app.route('/admin_logout')
def admin_logout():
    session.clear()
    jsonify({'message': 'Admin logged out successfully'})
    return render_template('admin_login.html')

if __name__ == '__main__':
    app.run(debug=True)
