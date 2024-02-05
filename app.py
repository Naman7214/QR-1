from flask import Flask, render_template, request, redirect, url_for, send_file, jsonify, session, g, flash
import threading
import time
import random
import qrcode
import io
import base64
import sqlite3
import re
from datetime import datetime, timedelta
from io import BytesIO
import plotly.graph_objs as go
from plotly.subplots import make_subplots
import google.generativeai as genai
import logging
from logging.handlers import RotatingFileHandler
from retry import retry

app = Flask(__name__)
app.config['DATABASE'] = 'students.db'
app.secret_key = '6NWMu7ewCqm7GX6tbG0hOJmU8QNWZ2A5'

GOOGLE_API_KEY= "AIzaSyA6Ga8yGLeMc7pCali3x8Hj3Itjk6ihAmQ"
genai.configure(api_key=GOOGLE_API_KEY)

logging.basicConfig(level=logging.DEBUG)
handler = RotatingFileHandler('app.log', maxBytes=10000, backupCount=1)
handler.setLevel(logging.DEBUG)
app.logger.addHandler(handler)


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


@retry(tries=3, delay=2, backoff=2)
def get_gemini_response(question,prompt):
    model = genai.GenerativeModel('gemini-pro')
    response=model.generate_content([prompt[0],question])
    return response.text

def read_sql_query(sql,db):
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute(sql)
    rows = cur.fetchall()
    conn.commit()
    conn.close()
    for row in rows:
        print(row)
    return rows

prompt1=[
    """
    Make sure you also respond to basic greetings from user by not trying them to convert to SQL query
    You are an expert in converting English questions to SQL query!
    The SQL database has the name students and has the following tables:


    \nCREATE TABLE students (
    roll_no VARCHAR(10) PRIMARY KEY,
    name VARCHAR(50),
    password VARCHAR(50)
    , elective1 VARCHAR(50), device_name TEXT, year VARCHAR, elective2 VARCHAR(50), Department VARCHAR) ,

Explanation:
Purpose of the table is to store information regarding all the students.
roll_no : represent roll number of the  student
name : Full name of the student in caps
password : login password for student (never write query to display this)
elective1 : 1st subject that student choose as an elective choice
elective2 : 2nd subject that student choose as an elective choice
device_name : Denotes the OS and device student is using to login.
Department : Department name to which student belongs to, possible values IT, AInDS and Electrical




\n CREATE TABLE QR_key (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_field VARCHAR(100)
    , teacher_id INTEGER) ,
Explaination:
Purpose of the table is to store the QR_key used for authentication of the QR code used by teacher, so that students can scan it and mark their attendance.
id :  Used as an index to fetch the latest key.
key_field : Actual Key value is stored here
teacher_id : Teacher's ID used to recognize which teacher generated this QR code.



\n CREATE TABLE Admins(
    Username VARCHAR(25) PRIMARY KEY,  
    Password VARCHAR(25),  
    Div VARCHAR(10),    
    Dept VARCHAR(50),  
    Class VARCHAR(10)        
    , teacher_id INTEGER, Acronym VARCHAR),

Explanation:
Purpose of this table is to store information regarding teachers such as their name, password, Department and etc..

Username : Denotes the first name of the teacher.
Password : Denotes teacher's login password (never write query to expose this password)
Div : Denotes the teacher teaches to which divison but it will always be NULL.
Dept :  Denotes the department to which teacher belongs.
Class : Denote the class to which teacher teaches and like divsion column this too would be NULL.
teacher_id:  ID used to unqiuely identify the teacher.
Acronym : Short form of teacher's full name for example Nikhil S Dhavase, his acronym NSD.




\n
    CREATE TABLE "IT_attendance"(
    rollno VARCHAR(20),
    stdname VARCHAR(25),
    subject VARCHAR(50),
    date DATE,
    time TIME,
    attendance BOOLEAN
    , teacher_id INTEGER, year VARCHAR, QR_time TEXT, Flag Boolean, TOS TOS VARCHAR),
Explanation:
This table stores attendance records of all  students of IT department.

rollno : Denotes roll number of the student.
stdname : Denotes student name.
subject : Denotes the subject for which the record exists.
date : Denotes the date for which the record exists.
time : Time Slot for which the lecture was conducted.
attendance : Denotes whether or not the student was present. 0 means absent and 1  means present
teacher_id :  helps identify which teacher took the lecture.
year : Denotes the student belongs to which year SE, TE or BE (i.e SECOND, THIRD or FOURTH).
QR_time: Time at which the QR was generated.
Flag : whether the alloted teacher took the lecture or someone else took the lecture. 0 indicates someone else took the lecture and 1 indicates the allocated teacher took the lecture.
TOS : Stands for time of scan and denotes the time at which student scaned the QR and marked his/her attendance.




\nCREATE TABLE "AInDS_attendance"(
    rollno VARCHAR(20),
    stdname VARCHAR(25),
    subject VARCHAR(50),
    date DATE,
    time TIME,
    attendance BOOLEAN
    , teacher_id INTEGER, year VARCHAR, QR_time TEXT, Flag Boolean, TOS TOS VARCHAR),

Explanation:
This table stores attendance records of all  students of AInDS department.

rollno : Denotes roll number of the student.
stdname : Denotes student name.
subject : Denotes the subject for which the record exists.
date : Denotes the date for which the record exists.
time : Time Slot for which the lecture was conducted.
attendance : Denotes whether or not the student was present. 0 means absent and 1  means present
teacher_id :  helps identify which teacher took the lecture.
year : Denotes the student belongs to which year SE, TE or BE (i.e SECOND, THIRD or FOURTH).
QR_time: Time at which the QR was generated.
Flag : whether the alloted teacher took the lecture or someone else took the lecture. 0 indicates someone else took the lecture and 1 indicates the allocated teacher took the lecture.
TOS : Stands for time of scan and denotes the time at which student scaned the QR and marked his/her attendance.



\n
    CREATE TABLE "Elec_attendance"(
    rollno VARCHAR(20),
    stdname VARCHAR(25),
    subject VARCHAR(50),
    date DATE,
    time TIME,
    attendance BOOLEAN
    , teacher_id INTEGER, year VARCHAR, QR_time TEXT, Flag Boolean, TOS TOS VARCHAR),

Explanation:
This table stores attendance records of all  students of Electrical department.

rollno : Denotes roll number of the student.
stdname : Denotes student name.
subject : Denotes the subject for which the record exists.
date : Denotes the date for which the record exists.
time : Time Slot for which the lecture was conducted.
attendance : Denotes whether or not the student was present. 0 means absent and 1  means present
teacher_id :  helps identify which teacher took the lecture.
year : Denotes the student belongs to which year SE, TE or BE (i.e SECOND, THIRD or FOURTH).
QR_time: Time at which the QR was generated.
Flag : whether the alloted teacher took the lecture or someone else took the lecture. 0 indicates someone else took the lecture and 1 indicates the allocated teacher took the lecture.
TOS : Stands for time of scan and denotes the time at which student scaned the QR and marked his/her attendance.


\n
    CREATE TABLE "IT_SE_TT" (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    subject TEXT,
    instructor TEXT,
    room TEXT,
    UNIQUE (day, time_slot)),

Explanation:
This table stores the time table for SE IT students.
id : used for indexing
day : denotes the day for which record exists.
time_slot : denotes the time slot of the lecture.
subject : denotes the subject name to be conducted for that record.
instructor : Teacher's Acronym who is responsible to conduct that lecture.
room : Room allocated for the lecture. This value would be NULL.



\n
    CREATE TABLE "IT_TE_TT" (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    subject TEXT,
    instructor TEXT,
    room TEXT,
    UNIQUE (day, time_slot)),


Explanation:
This table stores the time table for TE IT students.
id : used for indexing
day : denotes the day for which record exists.
time_slot : denotes the time slot of the lecture.
subject : denotes the subject name to be conducted for that record.
instructor : Teacher's Acronym who is responsible to conduct that lecture.
room : Room allocated for the lecture. This value would be NULL.




\n
    CREATE TABLE "IT_BE_TT" (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    subject TEXT,
    instructor TEXT,
    room TEXT,
    UNIQUE (day, time_slot)),


Explanation:
This table stores the time table for BE IT students.
id : used for indexing
day : denotes the day for which record exists.
time_slot : denotes the time slot of the lecture.
subject : denotes the subject name to be conducted for that record.
instructor : Teacher's Acronym who is responsible to conduct that lecture.
room : Room allocated for the lecture. This value would be NULL.



\n
    CREATE TABLE "Elec_SE_TT" (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    subject TEXT,
    instructor TEXT,
    room TEXT,
    UNIQUE (day, time_slot)),


Explanation:
This table stores the time table for SE Electrical students.
id : used for indexing
day : denotes the day for which record exists.
time_slot : denotes the time slot of the lecture.
subject : denotes the subject name to be conducted for that record.
instructor : Teacher's Acronym who is responsible to conduct that lecture.
room : Room allocated for the lecture. This value would be NULL.



\n
    CREATE TABLE "Elec_TE_TT" (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    subject TEXT,
    instructor TEXT,
    room TEXT,
    UNIQUE (day, time_slot)),

Explanation:
This table stores the time table for TE Electrical students.
id : used for indexing
day : denotes the day for which record exists.
time_slot : denotes the time slot of the lecture.
subject : denotes the subject name to be conducted for that record.
instructor : Teacher's Acronym who is responsible to conduct that lecture.
room : Room allocated for the lecture. This value would be NULL.



\n
    CREATE TABLE "Elec_BE_TT" (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    subject TEXT,
    instructor TEXT,
    room TEXT,
    UNIQUE (day, time_slot)),

Explanation:
This table stores the time table for BE Electrical students.
id : used for indexing
day : denotes the day for which record exists.
time_slot : denotes the time slot of the lecture.
subject : denotes the subject name to be conducted for that record.
instructor : Teacher's Acronym who is responsible to conduct that lecture.
room : Room allocated for the lecture. This value would be NULL.



\n
    CREATE TABLE "AInDS_SE_TT" (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    subject TEXT,
    instructor TEXT,
    room TEXT,
    UNIQUE (day, time_slot)),

Explanation:
This table stores the time table for SE AInDS students.
id : used for indexing
day : denotes the day for which record exists.
time_slot : denotes the time slot of the lecture.
subject : denotes the subject name to be conducted for that record.
instructor : Teacher's Acronym who is responsible to conduct that lecture.
room : Room allocated for the lecture. This value would be NULL.




\n
    CREATE TABLE "AInDS_TE_TT" (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    subject TEXT,
    instructor TEXT,
    room TEXT,
    UNIQUE (day, time_slot)),

Explanation:
This table stores the time table for TE AInDS students.
id : used for indexing
day : denotes the day for which record exists.
time_slot : denotes the time slot of the lecture.
subject : denotes the subject name to be conducted for that record.
instructor : Teacher's Acronym who is responsible to conduct that lecture.
room : Room allocated for the lecture. This value would be NULL.


ALso here is information regarding which subject belongs to which class

if department  == "IT":
        
        subjects_by_year = {
            'SE': ['DBMS', 'SE', 'EM-3', 'CG', 'PA'],
            'TE': ['DSBDA', 'CS', 'CC', 'CNS', 'WAD'],
            'BE': ['SnE', 'DS', 'NLP', 'BT', 'BAI', 'SC']
        }

if department == "AInDS":
        subjects_by_year = {
            'SE': ['STAT', 'DSA', 'IOT', 'MIS', 'SE'],
            'TE': ['DS', 'CS', 'ANN', 'SMA'],
        }

if department == "Electrical:
subjects_by_year = {
            'SE': ['PS-1', 'EM-1', 'NA', 'NMCP', 'FMA'],
            'TE': ['PS-2', 'CADEM', 'CSE', 'EM', 'PSD'],
            'BE': ['SGP', 'AEDC', 'SG', 'IL', 'PSD']
        }

Also here SE refers to second year, TE refers to Third year and BE means fourth and final year.


\n\nFor example, 


\nExample 1 - Retrieve the names of all students who have 'CC' as an elective and are in the 'IT' department. SQL Query: SELECT name FROM students WHERE elective1 = 'CC' AND Department = 'IT'; 
    \nExample 2 - Find the total number of students who were present in the 'ML' class on '2023-09-15'.
    SQL Query: SELECT COUNT(rollno) FROM AInDS_attendance WHERE subject = 'ML' AND date = '2023-09-15' AND attendance = TRUE;
    \nExample 3 - List the schedule of CNS class for TE IT on Wednesdays.
    SQL Query: SELECT day, time_slot, instructor, room FROM IT_TE_TT WHERE subject = 'CNS' AND day = 'Wednesday';
    \nExample 4 - Get the details of all teachers who have taught 'DSBDA' in the 'IT' department.
    SQL Query: SELECT DISTINCT instructor FROM IT_SE_TT WHERE subject = 'DSBDA' UNION SELECT DISTINCT instructor FROM IT_TE_TT WHERE subject = 'DSBDA' UNION SELECT DISTINCT instructor FROM IT_BE_TT WHERE subject = 'DSBDA';
    \nExample 5 - Identify students who have not attended any 'SE' classes in the current month.
    SQL Query: SELECT name FROM students WHERE Department = 'IT' AND roll_no NOT IN (SELECT rollno FROM IT_attendance WHERE subject = 'Operating Systems' AND date BETWEEN '2024-01-01' AND '2024-01-31' AND attendance = 1);
    \nExample 6 - Display the timetable for 'Third Year' students in the 'Electrical' department.
    SQL Query: SELECT * FROM Elec_TE_TT WHERE id IN (SELECT id FROM Elec_TE_TT GROUP BY day, time_slot HAVING COUNT(*) = 1);
    \n Note: under any circumstance do not write a query which might result in update, insert or delete operation.Also do not  write queries which might change the  database or manipulate the database only write queries which can display the infformation from the database
    if any such query is requested return this particular response "Can't do that!!"
    \nalso the sql code should not have ``` in beginning or end and sql word in output
    """


]


prompt2 = [
    """
    You are receiving a combined string of the user's query and the SQL query results. Your task is to understand the context of the user's query and the content of the SQL results, and then generate a response that is easy to understand by the user. The input format will be 'User query: [user's query]. SQL result: [SQL query results]'.

    Your response should focus on interpreting the SQL data in the context of the user's query. Ensure that your response is relevant to the user's original request and is framed in a way that is easily understandable.

    Also a note : the user doesn't know that that his reponse is being converted into query in order to display him any data. So keep it that way incase query is empty or something else.
    The SQL database has the name students and has the following tables:
        \nCREATE TABLE students (
    roll_no VARCHAR(10) PRIMARY KEY,
    name VARCHAR(50),
    password VARCHAR(50)
    , elective1 VARCHAR(50), device_name TEXT, year VARCHAR, elective2 VARCHAR(50), Department VARCHAR) ,

Explanation:
Purpose of the table is to store information regarding all the students.
roll_no : represent roll number of the  student
name : Full name of the student in caps
password : login password for student (never write query to display this)
elective1 : 1st subject that student choose as an elective choice
elective2 : 2nd subject that student choose as an elective choice
device_name : Denotes the OS and device student is using to login.
Department : Department name to which student belongs to, possible values IT, AInDS and Electrical




\n CREATE TABLE QR_key (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_field VARCHAR(100)
    , teacher_id INTEGER) ,
Explaination:
Purpose of the table is to store the QR_key used for authentication of the QR code used by teacher, so that students can scan it and mark their attendance.
id :  Used as an index to fetch the latest key.
key_field : Actual Key value is stored here
teacher_id : Teacher's ID used to recognize which teacher generated this QR code.



\n CREATE TABLE Admins(
    Username VARCHAR(25) PRIMARY KEY,  
    Password VARCHAR(25),  
    Div VARCHAR(10),    
    Dept VARCHAR(50),  
    Class VARCHAR(10)        
    , teacher_id INTEGER, Acronym VARCHAR),

Explanation:
Purpose of this table is to store information regarding teachers such as their name, password, Department and etc..

Username : Denotes the first name of the teacher.
Password : Denotes teacher's login password (never write query to expose this password)
Div : Denotes the teacher teaches to which divison but it will always be NULL.
Dept :  Denotes the department to which teacher belongs.
Class : Denote the class to which teacher teaches and like divsion column this too would be NULL.
teacher_id:  ID used to unqiuely identify the teacher.
Acronym : Short form of teacher's full name for example Nikhil S Dhavase, his acronym NSD.




\n
    CREATE TABLE "IT_attendance"(
    rollno VARCHAR(20),
    stdname VARCHAR(25),
    subject VARCHAR(50),
    date DATE,
    time TIME,
    attendance BOOLEAN
    , teacher_id INTEGER, year VARCHAR, QR_time TEXT, Flag Boolean, TOS TOS VARCHAR),
Explanation:
This table stores attendance records of all  students of IT department.

rollno : Denotes roll number of the student.
stdname : Denotes student name.
subject : Denotes the subject for which the record exists.
date : Denotes the date for which the record exists.
time : Time Slot for which the lecture was conducted.
attendance : Denotes whether or not the student was present. 0 means absent and 1  means present
teacher_id :  helps identify which teacher took the lecture.
year : Denotes the student belongs to which year SE, TE or BE (i.e SECOND, THIRD or FOURTH).
QR_time: Time at which the QR was generated.
Flag : whether the alloted teacher took the lecture or someone else took the lecture. 0 indicates someone else took the lecture and 1 indicates the allocated teacher took the lecture.
TOS : Stands for time of scan and denotes the time at which student scaned the QR and marked his/her attendance.




\nCREATE TABLE "AInDS_attendance"(
    rollno VARCHAR(20),
    stdname VARCHAR(25),
    subject VARCHAR(50),
    date DATE,
    time TIME,
    attendance BOOLEAN
    , teacher_id INTEGER, year VARCHAR, QR_time TEXT, Flag Boolean, TOS TOS VARCHAR),


Also here SE refers to second year, TE refers to Third year and BE means fourth and final year.

Explanation:
This table stores attendance records of all  students of AInDS department.

rollno : Denotes roll number of the student.
stdname : Denotes student name.
subject : Denotes the subject for which the record exists.
date : Denotes the date for which the record exists.
time : Time Slot for which the lecture was conducted.
attendance : Denotes whether or not the student was present. 0 means absent and 1  means present
teacher_id :  helps identify which teacher took the lecture.
year : Denotes the student belongs to which year SE, TE or BE (i.e SECOND, THIRD or FOURTH).
QR_time: Time at which the QR was generated.
Flag : whether the alloted teacher took the lecture or someone else took the lecture. 0 indicates someone else took the lecture and 1 indicates the allocated teacher took the lecture.
TOS : Stands for time of scan and denotes the time at which student scaned the QR and marked his/her attendance.



\n
    CREATE TABLE "Elec_attendance"(
    rollno VARCHAR(20),
    stdname VARCHAR(25),
    subject VARCHAR(50),
    date DATE,
    time TIME,
    attendance BOOLEAN
    , teacher_id INTEGER, year VARCHAR, QR_time TEXT, Flag Boolean, TOS TOS VARCHAR),

Explanation:
This table stores attendance records of all  students of Electrical department.

rollno : Denotes roll number of the student.
stdname : Denotes student name.
subject : Denotes the subject for which the record exists.
date : Denotes the date for which the record exists.
time : Time Slot for which the lecture was conducted.
attendance : Denotes whether or not the student was present. 0 means absent and 1  means present
teacher_id :  helps identify which teacher took the lecture.
year : Denotes the student belongs to which year SE, TE or BE (i.e SECOND, THIRD or FOURTH).
QR_time: Time at which the QR was generated.
Flag : whether the alloted teacher took the lecture or someone else took the lecture. 0 indicates someone else took the lecture and 1 indicates the allocated teacher took the lecture.
TOS : Stands for time of scan and denotes the time at which student scaned the QR and marked his/her attendance.


\n
    CREATE TABLE "IT_SE_TT" (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    subject TEXT,
    instructor TEXT,
    room TEXT,
    UNIQUE (day, time_slot)),

Explanation:
This table stores the time table for SE IT students.
id : used for indexing
day : denotes the day for which record exists.
time_slot : denotes the time slot of the lecture.
subject : denotes the subject name to be conducted for that record.
instructor : Teacher's Acronym who is responsible to conduct that lecture.
room : Room allocated for the lecture. This value would be NULL.



\n
    CREATE TABLE "IT_TE_TT" (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    subject TEXT,
    instructor TEXT,
    room TEXT,
    UNIQUE (day, time_slot)),


Explanation:
This table stores the time table for TE IT students.
id : used for indexing
day : denotes the day for which record exists.
time_slot : denotes the time slot of the lecture.
subject : denotes the subject name to be conducted for that record.
instructor : Teacher's Acronym who is responsible to conduct that lecture.
room : Room allocated for the lecture. This value would be NULL.




\n
    CREATE TABLE "IT_BE_TT" (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    subject TEXT,
    instructor TEXT,
    room TEXT,
    UNIQUE (day, time_slot)),


Explanation:
This table stores the time table for BE IT students.
id : used for indexing
day : denotes the day for which record exists.
time_slot : denotes the time slot of the lecture.
subject : denotes the subject name to be conducted for that record.
instructor : Teacher's Acronym who is responsible to conduct that lecture.
room : Room allocated for the lecture. This value would be NULL.



\n
    CREATE TABLE "Elec_SE_TT" (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    subject TEXT,
    instructor TEXT,
    room TEXT,
    UNIQUE (day, time_slot)),


Explanation:
This table stores the time table for SE Electrical students.
id : used for indexing
day : denotes the day for which record exists.
time_slot : denotes the time slot of the lecture.
subject : denotes the subject name to be conducted for that record.
instructor : Teacher's Acronym who is responsible to conduct that lecture.
room : Room allocated for the lecture. This value would be NULL.



\n
    CREATE TABLE "Elec_TE_TT" (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    subject TEXT,
    instructor TEXT,
    room TEXT,
    UNIQUE (day, time_slot)),

Explanation:
This table stores the time table for TE Electrical students.
id : used for indexing
day : denotes the day for which record exists.
time_slot : denotes the time slot of the lecture.
subject : denotes the subject name to be conducted for that record.
instructor : Teacher's Acronym who is responsible to conduct that lecture.
room : Room allocated for the lecture. This value would be NULL.



\n
    CREATE TABLE "Elec_BE_TT" (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    subject TEXT,
    instructor TEXT,
    room TEXT,
    UNIQUE (day, time_slot)),

Explanation:
This table stores the time table for BE Electrical students.
id : used for indexing
day : denotes the day for which record exists.
time_slot : denotes the time slot of the lecture.
subject : denotes the subject name to be conducted for that record.
instructor : Teacher's Acronym who is responsible to conduct that lecture.
room : Room allocated for the lecture. This value would be NULL.



\n
    CREATE TABLE "AInDS_SE_TT" (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    subject TEXT,
    instructor TEXT,
    room TEXT,
    UNIQUE (day, time_slot)),

Explanation:
This table stores the time table for SE AInDS students.
id : used for indexing
day : denotes the day for which record exists.
time_slot : denotes the time slot of the lecture.
subject : denotes the subject name to be conducted for that record.
instructor : Teacher's Acronym who is responsible to conduct that lecture.
room : Room allocated for the lecture. This value would be NULL.




\n
    CREATE TABLE "AInDS_TE_TT" (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    subject TEXT,
    instructor TEXT,
    room TEXT,
    UNIQUE (day, time_slot)),

Explanation:
This table stores the time table for TE AInDS students.
id : used for indexing
day : denotes the day for which record exists.
time_slot : denotes the time slot of the lecture.
subject : denotes the subject name to be conducted for that record.
instructor : Teacher's Acronym who is responsible to conduct that lecture.
room : Room allocated for the lecture. This value would be NULL.


ALso here is information regarding which subject belongs to which class

if department  == "IT":
        
        subjects_by_year = {
            'SE': ['DBMS', 'SE', 'EM-3', 'CG', 'PA'],
            'TE': ['DSBDA', 'CS', 'CC', 'CNS', 'WAD'],
            'BE': ['SnE', 'DS', 'NLP', 'BT', 'BAI', 'SC']
        }

if department == "AInDS":
        subjects_by_year = {
            'SE': ['STAT', 'DSA', 'IOT', 'MIS', 'SE'],
            'TE': ['DS', 'CS', 'ANN', 'SMA'],
        }

if department == "Electrical:
subjects_by_year = {
            'SE': ['PS-1', 'EM-1', 'NA', 'NMCP', 'FMA'],
            'TE': ['PS-2', 'CADEM', 'CSE', 'EM', 'PSD'],
            'BE': ['SGP', 'AEDC', 'SG', 'IL', 'PSD']
        }


    
    For example:
    - Input: "User query: List all students with Android devices. SQL result: ['John Doe; Android 10; Pixel 4']", 
      Response: "John Doe has an Android device, specifically a Pixel 4 running Android 10."
    - Input: "User query: Show attendance for the Machine Learning class on 2023-09-15. SQL result: ['15 ']", 
      Response: "On 2023-09-15, there were 15 students present in the Machine Learning class."
      
    """
]



def check_existing_records(subject_name, time_slot, date):

    department = session.get('admin_dept')

    if department == "IT":
    # Check if records already exist in IT_attendance
        existing_records = query_db('SELECT * FROM IT_attendance WHERE subject = ? AND time = ? AND date = ?',
                                (subject_name, time_slot, date))

    elif department == "AInDS":
        existing_records = query_db('SELECT * FROM AInDS_attendance WHERE subject = ? AND time = ? AND date = ?',
                                (subject_name, time_slot, date))

    else:
        existing_records = query_db('SELECT * FROM Elec_attendance WHERE subject = ? AND time = ? AND date = ?',
                                (subject_name, time_slot, date))

    return bool(existing_records)




# Function to generate a QR code based on teacher input
def generate_qr_code_from_input(subject_name, time_slot, date, year, instructor):
    key = generate_unique_key()

    # Insert the key into the QR_key table
    db = get_db()
    db.execute('INSERT INTO QR_key (key_field, teacher_id) VALUES (?, ?)', (key, session.get('teacher_id')))
    db.commit()


    teacher_id = session.get('teacher_id', None)
    Flag = 0
    
    if teacher_id is None:
        return {'error': 'Teacher ID not found in session'}

    current_time = datetime.now().time()
    current_time = current_time.strftime("%H:%M:%S")
    department = session.get('admin_dept', 'unknown')
    

    qr_data = f"{subject_name}_{time_slot}_{date}_{key}_{teacher_id}"
    print(qr_data)
    img_str = generate_qr_code(qr_data)

    session['qr_data'] = qr_data
    session['year'] = year
    session['subject_name'] = subject_name
    session['time_slot'] = time_slot
    session['date'] = date
    session['key'] = key
    session['teacher_id'] = teacher_id
    session['qr_image'] = img_str

    if department  == "IT":
        
        subjects_by_year = {
            'SE': ['DBMS', 'SE', 'EM-3', 'CG', 'PA'],
            'TE': ['DSBDA', 'CS', 'CC', 'CNS', 'WAD'],
            'BE': ['SnE', 'DS', 'NLP', 'BT', 'BAI', 'SC']
        }
    elif department == "AInDS":
        subjects_by_year = {
            'SE': ['STAT', 'DSA', 'IOT', 'MIS', 'SE'],
            'TE': ['DS', 'CS', 'ANN', 'SMA'],
        }

    else:
        subjects_by_year = {
            'SE': ['PS-1', 'EM-1', 'NA', 'NMCP', 'FMA'],
            'TE': ['PS-2', 'CADEM', 'CSE', 'EM', 'PSD'],
            'BE': ['SGP', 'AEDC', 'SG', 'IL', 'PSD']
        }

    if subject_name not in subjects_by_year.get(year, []):
        # Subject does not match the year
        return {'error': 'Invalid subject for the given year'}
    

    instructor_id = query_db('SELECT teacher_id FROM Admins WHERE Acronym = ? AND Dept = ?' , (instructor,department,))
    

    if instructor_id and 'teacher_id' in instructor_id[0]:
        if session['teacher_id'] == instructor_id[0]['teacher_id']:
            Flag = 1
        else:
            Flag = 0
    else:
        Flag = 0
        

    

    if department == 'IT':
        if year == 'SE':
            students = query_db('SELECT roll_no, name FROM students WHERE year =? and Department = ?', (year,department,))
            db = get_db()
            for student in students:
                db.execute('INSERT INTO IT_attendance (rollno, stdname, subject, date, time, attendance, teacher_id, year, QR_time, Flag) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (student['roll_no'], student['name'], subject_name, date, time_slot, 0, session['teacher_id'], year, current_time, Flag))
                
                db.commit()

        elif year == 'TE':
            if subject_name == "CS" or subject_name == "CC":
                students = query_db('SELECT roll_no, name FROM students WHERE elective1 = ?', (subject_name,))
                if students is not None:
                    db = get_db()
                    for student in students:
                        db.execute('INSERT INTO IT_attendance (rollno, stdname, subject, date, time, attendance, teacher_id, year, QR_time, Flag) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                (student['roll_no'], student['name'], subject_name, date, time_slot, 0, teacher_id, year, current_time, Flag))
                    db.commit()

            else:
                students = query_db('SELECT roll_no, name FROM students where year = ? AND Department = ?', (year, department,))
                db = get_db()
                for student in students:
                    db.execute('INSERT INTO IT_attendance (rollno, stdname, subject, date, time, attendance, teacher_id, year, QR_time, Flag) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (student['roll_no'], student['name'], subject_name, date, time_slot, 0, session['teacher_id'], year, current_time, Flag))

                db.commit()

        else:
            if subject_name == "NLP" or subject_name == "SC" or subject_name == "BAI" or subject_name == "BT":
                students = query_db('SELECT roll_no, name FROM students where elective1 =? OR elective2 = ?', (subject_name, subject_name,))
                if students is not None:
                    db = get_db()
                    for student in students:
                        db.execute('INSERT INTO IT_attendance (rollno, stdname, subject, date, time, attendance, teacher_id, year, QR_time, Flag) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (student['roll_no'], student['name'], subject_name, date, time_slot, 0, session['teacher_id'], year, current_time, Flag))
                    db.commit()
            else:
                students = query_db('SELECT roll_no, name FROM students where year = ? AND Department = ?', (year, department,))
                db = get_db()
                for student in students:
                    db.execute('INSERT INTO IT_attendance (rollno, stdname, subject, date, time, attendance, teacher_id, year, QR_time, Flag) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,, ?)',
                            (student['roll_no'], student['name'], subject_name, date, time_slot, 0, session['teacher_id'], year, current_time, Flag))
                db.commit()



    elif department == 'AInDS':
        if year == 'SE':
            students = query_db('SELECT roll_no, name FROM students WHERE year =? and Department = ?', (year,department,))
            db = get_db()
            for student in students:
                db.execute('INSERT INTO AInDS_attendance (rollno, stdname, subject, date, time, attendance, teacher_id, year, QR_time, Flag) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (student['roll_no'], student['name'], subject_name, date, time_slot, 0, session['teacher_id'], year, current_time, Flag))
                
                db.commit()

        elif year == 'TE':
                students = query_db('SELECT roll_no, name FROM students where year = ? AND Department = ?', (year, department,))
                db = get_db()
                for student in students:
                    db.execute('INSERT INTO AinDS_attendance (rollno, stdname, subject, date, time, attendance, teacher_id, year, QR_time, Flag) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (student['roll_no'], student['name'], subject_name, date, time_slot, 0, session['teacher_id'], year, current_time, Flag))

                db.commit()


    else:
        if year == 'SE':
            students = query_db('SELECT roll_no, name FROM students where year = ? AND Department = ?', (year, department,))
            db = get_db()
            for student in students:
                db.execute('INSERT INTO Elec_attendance (rollno, stdname, subject, date, time, attendance, teacher_id, year, QR_time, Flag) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (student['roll_no'], student['name'], subject_name, date, time_slot, 0, session['teacher_id'], year, current_time, Flag))
                
                db.commit()

        elif year == 'TE':
                students = query_db('SELECT roll_no, name FROM students where year = ? AND Department = ?', (year, department,))
                db = get_db()
                for student in students:
                    db.execute('INSERT INTO Elec_attendance (rollno, stdname, subject, date, time, attendance, teacher_id, year, QR_time, Flag) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (student['roll_no'], student['name'], subject_name, date, time_slot, 0, session['teacher_id'], year, current_time, Flag))

                db.commit()

        else:
                students = query_db('SELECT roll_no, name FROM students where year = ? AND Department = ?', (year, department,))
                db = get_db()
                for student in students:
                    db.execute('INSERT INTO Elec_attendance (rollno, stdname, subject, date, time, attendance, teacher_id, year, QR_time, Flag) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,, ?)',
                            (student['roll_no'], student['name'], subject_name, date, time_slot, 0, session['teacher_id'], year, current_time, Flag))
                db.commit()

    return {'qr_data': qr_data, 'qr_image': img_str}



def generate_analytics_data(week_start_date):
    # Convert week_start_date to a datetime object
    week_start = datetime.strptime(week_start_date, '%Y-%m-%d')

    # Calculate the end date of the week
    week_end = week_start + timedelta(days=6)

    department = session.get('admin_dept')
    if department == "Electrical":
        department = "Elec"

    if department in ["IT", "AInDS", "Elec"]:
        attendance_records = query_db(f"SELECT * FROM {department}_attendance WHERE date >= ? AND date <= ?", (week_start_date, week_end.strftime('%Y-%m-%d')))

        # Check if attendance_records is None or empty
        if not attendance_records:
            return "No attendance data available for the selected week."

        # Initialize dictionary to store total and present counts for each day
        day_wise_data = {day: {'total': 0, 'present': 0} for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']}

        for record in attendance_records:
            day_of_week = datetime.strptime(record['date'], '%Y-%m-%d').strftime('%A')
            # Increment total count for the day
            day_wise_data[day_of_week]['total'] += 1

            # Increment present count if attendance is 1
            if record['attendance'] == 1:
                day_wise_data[day_of_week]['present'] += 1

        # Calculate attendance percentage for each day
        attendance_percentage = {day: (day_data['present'] / day_data['total'] * 100) if day_data['total'] > 0 else 0 
                                 for day, day_data in day_wise_data.items()}

        # Create a bar graph using plotly
        fig = make_subplots(rows=1, cols=1, subplot_titles=[f'Attendance Percentage by Day of the Week (Week of {week_start_date})'])
        
        # Create the bar graph trace
        trace = go.Bar(x=list(attendance_percentage.keys()), y=list(attendance_percentage.values()), name='Attendance Percentage')

        # Set the y-axis range to 0 to 100
        fig.update_yaxes(range=[0, 100], title_text='Percentage')

        # Add the trace to the plot
        fig.add_trace(trace)

        # Convert the plot to HTML
        plot_html = fig.to_html(full_html=False)

        return plot_html

    else:
        # Handle the case where the department is not recognized
        raise ValueError("Unrecognized department")



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

    # Initialize 'department' with a default value or a value from session
    department = session.get('admin_dept', 'Unknown')

    if request.method == 'POST':
        subject_name = request.form['subject_name']
        time_slot = request.form['time_slot']
        date = request.form['date']
        year = request.form['year']
        instructor = request.form.get('instructor_info')

        if check_existing_records(subject_name, time_slot, date):
            error_message = "QR code generation failed. Records already exist for the selected data."
            flash(error_message, 'error')
            return redirect(request.referrer)  # Redirect to the referring URL

        result = generate_qr_code_from_input(subject_name, time_slot, date, year, instructor)

        if 'qr_data' in result:
            return render_template('index.html', qr_data=result['qr_data'], qr_image=result['qr_image'])
        else:
            error_message = "QR code generation failed. Please check the input parameters."
            flash(error_message, 'error')
            return redirect(request.referrer)  # Redirect to the referring URL

    return render_template('input.html', department=department)




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
                    return render_template('login.html', error='Device mismatch. Please log in from the registered device.')
            else:
                if device_name == "Linux; Android 10; K" or device_name == "Windows NT 10.0; Win64; x64":
                     return render_template('login.html', error='Please Login using Opera Browser Only and Not any other browser')
                else:
                    db = get_db()
                    db.execute('UPDATE students SET device_name = ? WHERE roll_no = ?', (device_name, roll_no))
                    db.commit()
                

            session['device_name'] = device_name

            # Create a session for the logged-in student
            session['roll_no'] = user['roll_no']
            session['name'] = user['name']
            session['department'] = user['Department']


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




@app.route('/it_te_tt')
def it_te_tt():
    if 'admin_username' not in session:
        # Redirect to login or any other appropriate route
        return redirect(url_for('admin_login'))
    timetable_data = query_db('SELECT * FROM IT_TE_TT ORDER BY day, time_slot')

    return render_template('it_te_tt.html',timetable_data = timetable_data)

@app.route('/it_se_tt')
def it_se_tt():
    if 'admin_username' not in session:
        # Redirect to login or any other appropriate route
        return redirect(url_for('admin_login'))
    timetable_data = query_db('SELECT * FROM IT_SE_TT ORDER BY day, time_slot')

    return render_template('it_se_tt.html',timetable_data = timetable_data)

@app.route('/it_be_tt')
def it_be_tt():
    if 'admin_username' not in session:
        # Redirect to login or any other appropriate route
        return redirect(url_for('admin_login'))
    timetable_data = query_db('SELECT * FROM IT_BE_TT ORDER BY day, time_slot')

    return render_template('it_be_tt.html',timetable_data = timetable_data)

@app.route('/elect_se_tt')
def elect_se_tt():
        if 'admin_username' not in session:
        # Redirect to login or any other appropriate route
            return redirect(url_for('admin_login'))

        timetable_data = query_db('SELECT * FROM Elec_SE_TT ORDER BY day, time_slot')
        return render_template('elect_se_tt.html',timetable_data = timetable_data)

@app.route('/elect_te_tt')
def elect_te_tt():
        if 'admin_username' not in session:
        # Redirect to login or any other appropriate route
            return redirect(url_for('admin_login'))
        timetable_data = query_db('SELECT * FROM Elec_TE_TT ORDER BY day, time_slot')
        return render_template('elect_te_tt.html',timetable_data = timetable_data)

@app.route('/elect_be_tt')
def elect_be_tt():
        if 'admin_username' not in session:
        # Redirect to login or any other appropriate route
            return redirect(url_for('admin_login'))
        timetable_data = query_db('SELECT * FROM Elec_BE_TT ORDER BY day, time_slot')
        return render_template('elect_be_tt.html',timetable_data = timetable_data)

@app.route('/ainds_se_tt')
def ainds_se_tt():
        if 'admin_username' not in session:
        # Redirect to login or any other appropriate route
            return redirect(url_for('admin_login'))
        timetable_data = query_db('SELECT * FROM AInDS_SE_TT ORDER BY day, time_slot')
        return render_template('ainds_se_tt.html',timetable_data = timetable_data)

@app.route('/ainds_te_tt')
def ainds_te_tt():
        if 'admin_username' not in session:
        # Redirect to login or any other appropriate route
            return redirect(url_for('admin_login'))
        timetable_data = query_db('SELECT * FROM AInDS_TE_TT ORDER BY day, time_slot')
        return render_template('ainds_te_tt.html',timetable_data = timetable_data)



@app.route('/Check_route')
def Check_route():

    department = session.get('admin_dept')
    print(department)

    if department == 'IT':
        return redirect(url_for('it_se_tt'))
    
    elif department == 'Electrical':
        return redirect(url_for('elect_se_tt'))

    else:
        return redirect(url_for('ainds_se_tt'))



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
    department = session.get('department')
    
    # Process the QR code and extract information
    qr_parts = qr_code.split('_')

    if len(qr_parts) == 5:
        subject_name, time_slot, date, key, teacher_id = qr_parts

        # Verify the key against the last generated key in QR_key for the specific session
        last_generated_key = query_db('SELECT key_field FROM QR_key WHERE teacher_id = ? ORDER BY id DESC LIMIT 1', (teacher_id,), one=True)

        if last_generated_key and key == last_generated_key['key_field']:
            
            if department == "IT":
               
                current_time = datetime.now().strftime('%I:%M:%S %p')

                # Key is valid, update attendance in IT_attendance for the logged-in student
                roll_no = session.get('roll_no')
                db = get_db()
                db.execute('UPDATE IT_attendance SET attendance = 1, TOS = ? WHERE rollno = ? AND subject = ? AND date = ? AND time = ? AND teacher_id = ?',
                        (current_time, roll_no, subject_name, date, time_slot, teacher_id))
                db.commit()

            elif department =="AInDS":
                current_time = datetime.now().strftime('%I:%M:%S %p')

                # Key is valid, update attendance in IT_attendance for the logged-in student
                roll_no = session.get('roll_no')
                db = get_db()
                db.execute('UPDATE AInDS_attendance SET attendance = 1, TOS = ? WHERE rollno = ? AND subject = ? AND date = ? AND time = ? AND teacher_id = ?',
                        (current_time, roll_no, subject_name, date, time_slot, teacher_id))
                db.commit()

            else:
                current_time = datetime.now().strftime('%I:%M:%S %p')

                # Key is valid, update attendance in IT_attendance for the logged-in student
                roll_no = session.get('roll_no')
                db = get_db()
                db.execute('UPDATE Elec_attendance SET attendance = 1, TOS = ? WHERE rollno = ? AND subject = ? AND date = ? AND time = ? AND teacher_id = ?',
                        (current_time, roll_no, subject_name, date, time_slot, teacher_id))
                db.commit()
            # Respond with a success message
            return jsonify({'message': 'QR code processed successfully'})

    # Invalid QR code format, key, or session ID
    return jsonify({'error': 'Invalid QR code format, key, or session ID'})


@app.route('/teacher_dashboard', methods=['POST', 'GET'])
def teacher_dashboard():
    # Check if the user is logged in as an admin
    if 'admin_username' not in session:
        # Redirect to the admin login page if not logged in
        return redirect(url_for('admin_login'))

    no_records_found = False
    department = session.get('admin_dept')

    if request.method == 'POST':
        # If it's a POST request, retrieve form data
        subject_name = request.form['subject_name']
        time_slot = request.form['time_slot']
        date = request.form['date']
        year = request.form['year']

        if department == "IT":
            
        # Run a query to fetch relevant records based on selected criteria
            records = query_db('SELECT * FROM IT_attendance WHERE subject = ? AND time = ? AND date = ? AND year = ?',
                            (subject_name, time_slot, date, year))
            
            if not records:
                no_records_found = True

        elif department =="AInDS":
            records = query_db('SELECT * FROM AInDS_attendance WHERE subject = ? AND time = ? AND date = ? AND year = ?',
                            (subject_name, time_slot, date, year))
            
            if not records:
                no_records_found = True


        else:
            records = query_db('SELECT * FROM Elec_attendance WHERE subject = ? AND time = ? AND date = ? AND year = ?',
                            (subject_name, time_slot, date, year))

            if not records:
                # No records found, set the flag
                no_records_found = True
                
            # Render the teacher_dashboard template with the fetched records or no records message
        return render_template('teacher_dashboard.html', records=records, no_records_found=no_records_found, department = department)

    # Admin is logged in, render the admin dashboard page (GET request)
    return render_template('teacher_dashboard.html', department = department)



@app.route('/update_attendance', methods=['POST'])
def update_attendance():
    if 'admin_username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    rollno = data.get('rollno')
    subject = data.get('subject')
    date = data.get('date')
    time = data.get('time')
    # No need to convert attendance as we're setting it directly to 1
    current_time = datetime.now().strftime('%I:%M:%S %p')
    department = session.get('admin_dept')

    # Check the current attendance status before updating
    if department == "IT":
        current_attendance = query_db('SELECT attendance FROM IT_attendance WHERE rollno = ? AND subject = ? AND date = ? AND time = ?', 
                                      (rollno, subject, date, time), one=True)
    elif department == "AInDS":
        current_attendance = query_db('SELECT attendance FROM AInDS_attendance WHERE rollno = ? AND subject = ? AND date = ? AND time = ?', 
                                      (rollno, subject, date, time), one=True)
    else:  # Assuming "Electrical" or other departments
        current_attendance = query_db('SELECT attendance FROM Elec_attendance WHERE rollno = ? AND subject = ? AND date = ? AND time = ?', 
                                      (rollno, subject, date, time), one=True)

    # Proceed to update only if the current attendance is 0
    if current_attendance and current_attendance['attendance'] == 0:
        db = get_db()
        if department == "IT":
            db.execute('UPDATE IT_attendance SET attendance = 1, TOS = ? WHERE rollno = ? AND subject = ? AND date = ? AND time = ?', 
                       (current_time, rollno, subject, date, time))
        elif department == "AInDS":
            db.execute('UPDATE AInDS_attendance SET attendance = 1, TOS = ? WHERE rollno = ? AND subject = ? AND date = ? AND time = ?', 
                       (current_time, rollno, subject, date, time))
        else:  # Assuming "Electrical" or other departments
            db.execute('UPDATE Elec_attendance SET attendance = 1, TOS = ? WHERE rollno = ? AND subject = ? AND date = ? AND time = ?', 
                       (current_time, rollno, subject, date, time))
        db.commit()
        return jsonify({'message': 'Attendance updated successfully to present'})
    else:
        # If attendance is already marked as 1, do not update
        return jsonify({'message': 'Attendance is already marked as present or record not found'})



@app.route('/attendance_summary', methods=['POST'])
def attendance_summary():
    # Check if the user is logged in as an admin
    if 'admin_username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.form
    date = data.get('date')
    year = data.get('year')
    department = session.get('admin_dept')

    # Initialize subject_counts dictionary to store attendance summary and time slots


    subject_counts = {}

    if department == "IT":
        if year in ["SE", "TE", "BE"]:

            if year == "SE":
                subjects = ['EM-3', 'DBMS', 'SE', 'PA', 'CG']
            elif year == "TE":
                subjects = ['WAD', 'DSBDA', 'CC', 'CS', 'CNS']
            else:
                subjects = ['SnE', 'NLP', 'BAI', 'BT', 'DS']


            
            # Fetch distinct time slots for each subject on the given date
            for subject in subjects:
                time_slot_results = query_db('SELECT DISTINCT time FROM IT_attendance WHERE subject = ? AND date = ? AND year = ?' , (subject, date, year))
                
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
                        summary = query_db('SELECT attendance, COUNT(*) as count FROM IT_attendance WHERE subject = ? AND date = ? AND time = ?  AND year = ? GROUP BY attendance', (subject, date, time_slot, year))
                        for row in summary:
                            if row['attendance'] == 1:
                                subject_counts[subject][time_slot]['present_count'] = row['count']
                            elif row['attendance'] == 0:
                                subject_counts[subject][time_slot]['absent_count'] = row['count']


    elif department == "AInDS":
         if year in ["SE", "TE", "BE"]:

            if year == "SE":
                subjects = ['STAT', 'DSA', 'IOT', 'MIS', 'SE']
            else:
                subjects = ['DS', 'CS', 'ANN', 'SMA']
            
            for subject in subjects:
                time_slot_results = query_db('SELECT DISTINCT time FROM AInDS_attendance WHERE subject = ? AND date = ? AND year = ?' , (subject, date, year))
                
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
                        summary = query_db('SELECT attendance, COUNT(*) as count FROM AInDS_attendance WHERE subject = ? AND date = ? AND time = ?  AND year = ? GROUP BY attendance', (subject, date, time_slot, year))
                        for row in summary:
                            if row['attendance'] == 1:
                                subject_counts[subject][time_slot]['present_count'] = row['count']
                            elif row['attendance'] == 0:
                                subject_counts[subject][time_slot]['absent_count'] = row['count']
        

    else :
        if year in ["SE", "TE", "BE"]:
            
            if year == "SE":
                subjects = ['PS-1', 'EM-1', 'NA', 'NMCP', 'FMA']
            elif year == "TE":
                subjects = ['PS-2', 'CADEM', 'CSE', 'EM', 'PSD']
            else:
                subjects = ['SGP', 'AEDC', 'SG', 'IL', 'PSD']

            # Fetch distinct time slots for each subject on the given date
            for subject in subjects:
                time_slot_results = query_db('SELECT DISTINCT time FROM Elec_attendance WHERE subject = ? AND date = ? AND year = ?' , (subject, date, year))

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
                        summary = query_db('SELECT attendance, COUNT(*) as count FROM Elec_attendance WHERE subject = ? AND date = ? AND time = ?  AND year = ? GROUP BY attendance', (subject, date, time_slot, year))
                    
                        for row in summary:
                            if row['attendance'] == 1:
                                subject_counts[subject][time_slot]['present_count'] = row['count']
                            elif row['attendance'] == 0:
                                subject_counts[subject][time_slot]['absent_count'] = row['count']



    return jsonify(subject_counts)




@app.route('/analytics', methods=['GET', 'POST'])
def analytics():
    if 'admin_username' not in session:
        return redirect(url_for('admin_login'))
    department = session.get('admin_dept')
    analytics_data = ''
    error_message = ''

    if request.method == 'POST':
        week_start_date = request.form.get('week_start')
        analytics_data = generate_analytics_data(week_start_date)
        if isinstance(analytics_data, str) and analytics_data.startswith("No attendance data"):
            error_message = analytics_data
            analytics_data = ''

    return render_template('analytics.html', plot_html=analytics_data, error_message=error_message,department=department)


@app.route('/attendance_summary_by_student', methods=['GET', 'POST'])
def attendance_summary_by_student():
    if 'admin_username' not in session:
        return redirect(url_for('admin_login'))

    department = session.get('admin_dept')

    if request.method == 'POST':
        year = request.form['year']
        start_date = request.form['start_date']
        end_date = request.form['end_date']

        if not (year and start_date and end_date):
            return jsonify({'error': 'Missing required fields'}), 400

        # Fetch all students of the specified year
        students = query_db('SELECT roll_no FROM students WHERE year = ? AND Department = ?', (year, department,))
        if not students:  # Check if students is None or empty
            return jsonify({'error': 'No students found'}), 404

        attendance_summary = {}
        if department == "Electrical":
            department = "Elec"

        if department in ["IT", "AInDS", "Elec"]:
            # Fetch attendance records
            records = query_db(f'''SELECT rollno, subject, COUNT(*) as lectures_attended 
                                   FROM {department}_attendance 
                                   WHERE year = ? AND date BETWEEN ? AND ? AND attendance = 1 
                                   GROUP BY rollno, subject''', 
                               (year, start_date, end_date))
            if not records:  # Check if records is None or empty
                return jsonify({'error': 'No attendance records found'}), 404

            # Fetch total lecture count for each subject
            total_lectures_query = query_db(f'''SELECT subject, COUNT(DISTINCT date) as total_lectures 
                                                FROM {department}_attendance 
                                                WHERE year = ? AND date BETWEEN ? AND ? 
                                                GROUP BY subject''',
                                            (year, start_date, end_date))
            if not total_lectures_query:  # Check if total_lectures_query is None or empty
                return jsonify({'error': 'No lecture data found'}), 404

            total_lectures = {item['subject']: item['total_lectures'] for item in total_lectures_query}

            # Initialize attendance summary for each student
            attendance_summary = {student['roll_no']: {subject: 0 for subject in total_lectures} for student in students}

            # Populate attendance summary with actual data
            for record in records:
                roll_no = record['rollno']
                subject = record['subject']
                lectures_attended = record['lectures_attended']
                if roll_no in attendance_summary:
                    attendance_summary[roll_no][subject] = lectures_attended

            return render_template('attendance_summary.html', 
                                attendance_summary=attendance_summary, 
                                total_lectures=total_lectures)

    return render_template('attendance.html')





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


@app.route('/reset', methods=['GET','POST'])
def reset():

    return render_template('reset.html')

@app.route('/reset_password', methods=['GET','POST'])
def reset_password():
    
    admin_name = session.get('admin_username')

    if request.method == 'POST':
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        # Check if passwords match
        if new_password != confirm_password:
            flash('Passwords do not match!', 'error')
            return redirect(url_for('reset'))
        
        db = get_db()
        db.execute('UPDATE Admins SET Password = ? WHERE Username = ? ', (new_password,admin_name))
        db.commit()

        flash('Password successfully updated!', 'success')
        return redirect(url_for('admin_login'))
    
    return redirect(url_for('reset'))

@app.route('/prompt', methods=['GET', 'POST'])
def prompt():
    if request.method == 'POST':
        user_input = request.form['textInput']
        
        # Get the SQL query response
        sql_response = get_gemini_response(user_input, prompt1)
        print(sql_response)
        
        if sql_response == "Can't do that!!":
            return render_template('prompt.html', user_input=user_input, response=sql_response)

        # Check if the response is a valid SQL query
        try:
            # Attempt to execute the SQL query and format the result
            sql_query_result = read_sql_query(sql_response, "students.db")
            formatted_sql_result = ', '.join([' '.join(map(str, row)) for row in sql_query_result])

            # Combine user input and SQL query result for context
            combined_context = f"User query: {user_input}. SQL result: {formatted_sql_result}"

            # Pass the combined context for the final response
            final_response = get_gemini_response(combined_context, prompt2)

            return render_template('prompt.html', user_input=user_input, response=final_response)

        except Exception as e:
            # If there's an exception, it means the response is not a valid SQL query
            # Handle the situation by printing the text
            print(f"Response is not a valid SQL query: {sql_response}")
            return render_template('prompt.html', user_input=user_input, response=sql_response)

    return render_template('prompt.html', response=None)


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