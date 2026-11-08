"""Serves the setup page.

The setup page now sends Trig Protocol (1) straight to the FastAPI backend
(main.py on :8000); this server only serves index.html.

Run:   pip install flask
       python server.py
Open:  http://localhost:5000
"""
from flask import Flask, send_file

app = Flask(__name__)


@app.get("/")
def index():
    return send_file("index.html")


if __name__ == "__main__":
    app.run(debug=True)
