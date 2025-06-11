from flask import Flask, render_template, request, redirect, url_for, flash, send_file
import psycopg2
from dotenv import load_dotenv
import os
import qrcode
from barcode import Code128
from barcode.writer import ImageWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from io import BytesIO
from PIL import Image
from datetime import datetime
import psycopg2.extras
from psycopg2.extras import DictCursor




load_dotenv()

app = Flask(__name__)
app.secret_key = 'rahasia'



def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        cursor_factory=psycopg2.extras.DictCursor  # PENTING
    )

@app.route('/test-db')
def test_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT NOW()")
        result = cur.fetchone()
        conn.close()
        return f"Database OK! Waktu server: {result[0]}"
    except Exception as e:
        return f"Database ERROR: {str(e)}"

@app.route('/')
@app.route('/event/list')
def index():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM event ORDER BY id DESC")
    events = cur.fetchall()
    conn.close()
    return render_template('index.html', events=events)


@app.route('/event/form')
def tambah_event_form():
    return render_template('tambah_tiket.html')

@app.route('/event', methods=['POST'])
def tambah_event():
    nama = request.form['nama']
    tanggal = request.form['tanggal']
    lokasi = request.form['lokasi']

    kategori_nama = request.form.getlist('kategori_nama[]')
    kategori_jumlah = request.form.getlist('kategori_jumlah[]')
    kategori_background = request.files.getlist('kategori_background[]')

    conn = get_db_connection()
    cur = conn.cursor()

    # Insert event terlebih dahulu
    cur.execute(
        "INSERT INTO event (nama_event, tanggal, lokasi) VALUES (%s, %s, %s) RETURNING id",
        (nama, tanggal, lokasi)
    )
    event_id = cur.fetchone()[0]

    total_tiket = 0  # <--- Tambahkan ini

    for i in range(len(kategori_nama)):
        nama_kat = kategori_nama[i]
        jumlah = int(kategori_jumlah[i])
        file = kategori_background[i]

        filename = f"{event_id}_{nama_kat.replace(' ', '_').lower()}.jpg"
        filepath = os.path.join('static', 'event_bg', filename)
        file.save(filepath)

        # Insert ke kategori_tiket
        cur.execute("""
            INSERT INTO kategori_tiket (event_id, nama_kategori, jumlah, background)
            VALUES (%s, %s, %s, %s)
        """, (event_id, nama_kat, jumlah, filename))

        total_tiket += jumlah  # <--- Hitung total tiket

    # Update jumlah_tiket di event
    cur.execute("UPDATE event SET jumlah_tiket = %s WHERE id = %s", (total_tiket, event_id))

    conn.commit()
    conn.close()

    flash('Event dan kategori tiket berhasil ditambahkan!')
    return redirect(url_for('index'))


@app.route('/list_tiket')
def list_tiket():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT e.id, e.nama_event, COALESCE(SUM(k.jumlah), 0) AS jumlah_tiket
        FROM event e
        LEFT JOIN kategori_tiket k ON e.id = k.event_id
        GROUP BY e.id, e.nama_event
        ORDER BY e.id DESC
    ''')
    events = cur.fetchall()
    conn.close()
    return render_template('list_tiket.html', events=events)






@app.route("/generate_tiket/<int:event_id>")
def generate_tiket(event_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM event WHERE id = %s', (event_id,))
    event = cur.fetchone()
    
    if not event:
        return "Event tidak ditemukan", 404
    jumlah_tiket = event['jumlah_tiket']
    nama_event = event['nama_event']

    # Ukuran halaman PDF (A4)
    width, height = A4
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)

    # Koordinat awal
    x_start = 40
    y_start = height - 100
    x = x_start
    y = y_start
    kolom = 3
    baris_per_halaman = 5
    tiket_per_halaman = kolom * baris_per_halaman
    counter = 0

    for i in range(1, jumlah_tiket + 1):
        kode = f"{event_id:03d}-{i:04d}"

        # QR Code
        qr = qrcode.make(kode)
        qr_path = f"temp/qr_{kode}.png"
        qr.save(qr_path)

        # Barcode
        CODE128 = barcode.get_barcode_class('code128')
        code128 = CODE128(kode, writer=ImageWriter())
        barcode_path = f"temp/barcode_{kode}.png"
        code128.save(barcode_path)

        # Gambar QR dan Barcode ke canvas
        c.rect(x - 10, y - 10, 170, 120)  # border tiket
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x, y + 100, f"Event: {nama_event}")
        c.drawString(x, y + 85, f"Kode: {kode}")
        c.drawImage(qr_path, x, y + 10, width=50, height=50)
        c.drawImage(barcode_path, x + 60, y + 10, width=100, height=40)

        # Hapus gambar sementara
        os.remove(qr_path)
        os.remove(barcode_path)

        # Geser ke posisi berikutnya
        if (i % kolom) == 0:
            x = x_start
            y -= 130
        else:
            x += 190

        counter += 1
        if counter == tiket_per_halaman:
            c.showPage()
            x = x_start
            y = y_start
            counter = 0

    c.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"{nama_event}_tiket.pdf", mimetype='application/pdf')
if __name__ == '__main__':
    app.run(debug=True)