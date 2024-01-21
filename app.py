from flask import Flask, render_template, request, redirect, url_for, send_file, jsonify, session, g, flash
import threading
import time
import random
import qrcode
import io
import base64
import sqlite3
import re
from datetime import datetime


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


def generate_device_identifier():
    return request.headers.get('User-Agent')


# Function to generate a QR code
def generate_qr_code(qr_data):
    img = qrcode.make(qr_data)
    img_buffer = io.BytesIO()
    img.save(img_buffer)
    img_str = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
    return img_str


def check_existing_records(subject_name, time_slot, date):
    teacher_id = session.get('teacher_id') 

    # Check if records already exist in Temp_attendance
    existing_records = query_db('SELECT * FROM Temp_attendance WHERE subject = ? AND time = ? AND date = ? AND teacher_id = ?',
                                (subject_name, time_slot, date, teacher_id))

    return bool(existing_records)



# Function to generate a QR code based on teacher input
def generate_qr_code_from_input(subject_name, time_slot, date, year):
    key = generate_unique_key()

    # Insert the key into the QR_key table
    db = get_db()
    db.execute('INSERT INTO QR_key (key_field, teacher_id) VALUES (?, ?)', (key, session.get('teacher_id')))
    db.commit()

    teacher_id = session.get('teacher_id', None)
    
    if teacher_id is None:
        return {'error': 'Teacher ID not found in session'}

    current_time = datetime.now().time()
    current_time = current_time.strftime("%H:%M:%S")

    qr_data = f"{subject_name}_{time_slot}_{date}_{key}_{teacher_id}"

    img_str = generate_qr_code(qr_data)

    session['qr_data'] = qr_data
    session['year'] = year
    session['subject_name'] = subject_name
    session['time_slot'] = time_slot
    session['date'] = date
    session['key'] = key
    session['teacher_id'] = teacher_id
    session['qr_image'] = img_str

    subjects_by_year = {
        'SE': ['DBMS', 'SE', 'EM-3', 'CG', 'PA'],
        'TE': ['DSBDA', 'CS', 'CC', 'CNS', 'WAD'],
        'BE': ['SnE', 'DS', 'NLP', 'BT', 'BAI', 'SC']
    }

    if subject_name not in subjects_by_year.get(year, []):
        # Subject does not match the year
        return {'error': 'Invalid subject for the given year'}

    if year == 'SE':
        students = query_db('SELECT roll_no, name FROM students WHERE year =?', (year,))
        db = get_db()
        for student in students:
            db.execute('INSERT INTO Temp_attendance (rollno, stdname, subject, date, time, attendance, teacher_id, year, QR_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (student['roll_no'], student['name'], subject_name, date, time_slot, 0, session['teacher_id'], year, current_time))
            
            db.commit()

    elif year == 'TE':
        if subject_name == "CS" or subject_name == "CC":
            students = query_db('SELECT roll_no, name FROM students WHERE elective1 = ?', (subject_name,))
            if students is not None:
                db = get_db()
                for student in students:
                    db.execute('INSERT INTO Temp_attendance (rollno, stdname, subject, date, time, attendance, teacher_id, year, QR_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (student['roll_no'], student['name'], subject_name, date, time_slot, 0, teacher_id, year, current_time))
                db.commit()

        else:
            students = query_db('SELECT roll_no, name FROM students where year = ?', (year,))
            db = get_db()
            for student in students:
                db.execute('INSERT INTO Temp_attendance (rollno, stdname, subject, date, time, attendance, teacher_id, year, QR_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (student['roll_no'], student['name'], subject_name, date, time_slot, 0, session['teacher_id'], year, current_time))

            db.commit()
    
    else:
        if subject_name == "NLP" or subject_name == "SC" or subject_name == "BAI" or subject_name == "BT":
            students = query_db('SELECT roll_no, name FROM students where elective1 =? OR elective2 = ?', (subject_name, subject_name,))
            if students is not None:
                db = get_db()
                for student in students:
                    db.execute('INSERT INTO Temp_attendance (rollno, stdname, subject, date, time, attendance, teacher_id, year, QR_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (student['roll_no'], student['name'], subject_name, date, time_slot, 0, session['teacher_id'], year, current_time))
                db.commit()
        else:
            students = query_db('SELECT roll_no, name from students where year = ?', (year,))
            db = get_db()
            for student in students:
                db.execute('INSERT INTO Temp_attendance (rollno, stdname, subject, date, time, attendance, teacher_id, year, QR_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (student['roll_no'], student['name'], subject_name, date, time_slot, 0, session['teacher_id'], year, current_time))
            db.commit()

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

    # Get information from the session instead of attendance_status
    # year = session.get('year', 'Unknown')
    subject_name = session.get('subject_name', 'Unknown')
    time_slot = session.get('time_slot', 'Unknown')
    date = session.get('date', 'Unknown')
    teacher_id = session.get('teacher_id', 'Unknown')

    qr_data = f"{subject_name}_{time_slot}_{date}_{key}_{teacher_id}"
    img_str = generate_qr_code(qr_data)

    # Update session with new information
    session['qr_data'] = qr_data
    session['key'] = key
    session['qr_image'] = img_str

    # Insert the key into the QR_key table
    db = get_db()
    db.execute('INSERT INTO QR_key (key_field, teacher_id) VALUES (?, ?)', (key, teacher_id))
    db.commit()

    return "QR code generated successfully"


# Route to serve the QR code image
@app.route('/qr_image')
def qr_image():
    # Retrieve the QR image from the session
    qr_image_data = session.get('qr_image', '')

    # Send the file using Flask's send_file function
    return send_file(io.BytesIO(base64.b64decode(qr_image_data)), mimetype='image/png')



# Route to display the input page for the teacher
@app.route('/input', methods=['GET', 'POST'])
def input():
    if 'admin_username' not in session:
        # Redirect to login or any other appropriate route
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        subject_name = request.form['subject_name']
        time_slot = request.form['time_slot']
        date = request.form['date']
        year = request.form['year']

        if check_existing_records(subject_name, time_slot, date):
            error_message = "QR code generation failed. Records already exist for the selected data."
            
            # Flash the error message
            flash(error_message, 'error')

            # Redirect to the referring URL
            return redirect(request.referrer)  # Redirect to the referring URL

        result = generate_qr_code_from_input(subject_name, time_slot, date, year)

        # Check if 'qr_data' exists in the result dictionary
        if 'qr_data' in result:
            return render_template('index.html', qr_data=result['qr_data'], qr_image=result['qr_image'])
        else:
            # Handle the case where 'qr_data' is not present in the result
            error_message = "QR code generation failed. Please check the input parameters."
            
            # Flash the error message
            flash(error_message, 'error')

            # Redirect to the referring URL
            return redirect(request.referrer)  # Redirect to the referring URL

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
        device_name = generate_device_identifier()
        device_name = re.findall(r'\(([^)]+)\)', device_name)[0]

        user = query_db('SELECT * FROM students WHERE roll_no = ?', (roll_no,), one=True)

        # Check if the user exists and the password is correct
        if user and user['password'] == password:
            if user['device_name'] is not None:
                # Compare the current device name with the one in the database
                if device_name not in user['device_name']:
                    # Device names do not match, return an error
                    print(device_name[0])
                    return render_template('login.html', error='Device mismatch. Please log in from the registered device.')
            else:
                print(device_name)
                db = get_db()
                db.execute('UPDATE students SET device_name = ? WHERE roll_no = ?', (device_name, roll_no))
                db.commit()
                
            # Update the session with the current device_name
            session['device_name'] = device_name

            # Create a session for the logged-in student
            session['roll_no'] = user['roll_no']
            session['name'] = user['name']

            # Redirect to the QR scanner page after successful login
            return render_template('qr_scanner.html', device_name=device_name)
        else:
            # Incorrect roll number or password
            return render_template('login.html', error='Invalid roll number or password')

    # Handle the case when the request method is not POST
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
    
    name = session.get('admin_username')

    return render_template('admin_options.html', name = name)

@app.route('/te_tt')
def te_tt():
    timetable_data = query_db('SELECT * FROM TE_TT ORDER BY day, time_slot')

    return render_template('te_tt.html',timetable_data = timetable_data)

@app.route('/se_tt')
def se_tt():
    timetable_data = query_db('SELECT * FROM SE_TT ORDER BY day, time_slot')

    return render_template('se_tt.html',timetable_data = timetable_data)

@app.route('/be_tt')
def be_tt():
    timetable_data = query_db('SELECT * FROM BE_TT ORDER BY day, time_slot')

    return render_template('be_tt.html',timetable_data = timetable_data)


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
        year = request.form['year']

        # Run a query to fetch relevant records based on selected criteria
        records = query_db('SELECT * FROM Temp_attendance WHERE subject = ? AND time = ? AND date = ? AND year = ?',
                           (subject_name, time_slot, date, year))

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


@app.route('/attendance_summary', methods=['POST'])
def attendance_summary():
    # Check if the user is logged in as an admin
    if 'admin_username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.form
    date = data.get('date')
    year = data.get('year')

    # Initialize subject_counts dictionary to store attendance summary and time slots
    subject_counts = {}

    if year in ["SE", "TE", "BE"]:
        if year == "SE":
            subjects = ['EM-3', 'DBMS', 'SE', 'PA', 'CG']
        elif year == "TE":
            subjects = ['WAD', 'DSBDA', 'CC', 'CS', 'CNS']
        else:
            subjects = ['SnE', 'NLP', 'BAI', 'BT', 'DS']

        # Fetch distinct time slots for each subject on the given date
        for subject in subjects:
            time_slot_results = query_db('SELECT DISTINCT time FROM Temp_attendance WHERE subject = ? AND date = ? AND year = ?' , (subject, date, year))

            # Check if time_slot_results is not None before proceeding
            if time_slot_results is not None:
                # Process the summary data for the subject and each time slot
                for time_slot_result in time_slot_results:
                    time_slot = time_slot_result['time']

                    if subject not in subject_counts:
                        subject_counts[subject] = {}

                    subject_counts[subject][time_slot] = {
                        'present_count': 0,
                        'absent_count': 0,
                    }

                    # Fetch attendance summary for the subject and time slot
                    summary = query_db('SELECT attendance, COUNT(*) as count FROM Temp_attendance WHERE subject = ? AND date = ? AND time = ?  AND year = ? GROUP BY attendance', (subject, date, time_slot, year))
                
                    for row in summary:
                        if row['attendance'] == 1:
                            subject_counts[subject][time_slot]['present_count'] = row['count']
                        elif row['attendance'] == 0:
                            subject_counts[subject][time_slot]['absent_count'] = row['count']

    return jsonify(subject_counts)






@app.route('/studentcnt')
def studentcnt():
    return render_template('studentcnt.html')



@app.route('/profile')
def profile():
    name = session.get('name')
    roll_no = session.get('roll_no')
    user_ip = session.get('user_ip')
    device_name = session.get('device_name')  # Generate device_name here or retrieve it from session
    return jsonify({'username': name, 'roll_no': roll_no, 'user_ip': user_ip, 'device_name': device_name})


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

@app.route('/developers')
def developers():
    return render_template('developers.html')

if __name__ == '__main__':
    app.run(debug=True)