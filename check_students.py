
from pymongo import MongoClient

# Connect to MongoDB
client = MongoClient('mongodb://localhost:27017/')
db = client['timetable_db']

# Retrieve and print all student documents
students = db.students.find()
for student in students:
    print(student)
