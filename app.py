import barcode
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
from pathlib import Path
from reportlab.graphics.barcode import code128




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

    # Tambah event
    cur.execute("INSERT INTO event (nama_event, tanggal, lokasi) VALUES (%s, %s, %s) RETURNING id", 
                (nama, tanggal, lokasi))
    event_id = cur.fetchone()[0]

    total_tiket = 0

    # Tambah kategori_tiket
    for i in range(len(kategori_nama)):
        nama_kat = kategori_nama[i]
        jumlah = int(kategori_jumlah[i])
        file = kategori_background[i]

        total_tiket += jumlah  # akumulasi total tiket

        filename = f"{event_id}_{nama_kat.replace(' ', '_').lower()}.jpg"
        filepath = os.path.join('static', 'event_bg', filename)
        file.save(filepath)

        cur.execute("""
            INSERT INTO kategori_tiket (event_id, nama_kategori, jumlah, background)
            VALUES (%s, %s, %s, %s)
        """, (event_id, nama_kat, jumlah, filename))

    # Update kolom jumlah_tiket di tabel event
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
    from reportlab.lib.units import mm
    import os

    conn = get_db_connection()
    cur = conn.cursor()

    # Ambil data event
    cur.execute('SELECT * FROM event WHERE id = %s', (event_id,))
    event = cur.fetchone()
    if not event:
        return "Event tidak ditemukan", 404

    jumlah_tiket = event['jumlah_tiket']
    nama_event = event['nama_event']

    # Ambil kategori dan background
    cur.execute('SELECT * FROM kategori_tiket WHERE event_id = %s ORDER BY id ASC', (event_id,))
    kategori_list = cur.fetchall()

    # Siapkan PDF
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Ukuran tiket (dalam mm)
    tiket_width = 200 * mm
    tiket_height = 20 * mm
    margin_x = 20
    margin_y = 20
    x = margin_x
    y = height - tiket_height - margin_y

    tiket_per_halaman = int((height - margin_y * 2) // (tiket_height + 5))

    # Inisialisasi kategori
    kat_index = 0
    kat_counter = 0
    kat_max = kategori_list[kat_index]['jumlah']
    kategori_nama = kategori_list[kat_index]['nama_kategori']
    background_path = os.path.join("static", "event_bg", kategori_list[kat_index]['background'])

    for i in range(1, jumlah_tiket + 1):
        kode = f"{event_id:03d}-{i:04d}"

        # Ganti kategori jika sudah penuh
        if kat_counter >= kat_max and kat_index < len(kategori_list) - 1:
            kat_index += 1
            kat_counter = 0
            kat_max = kategori_list[kat_index]['jumlah']
            kategori_nama = kategori_list[kat_index]['nama_kategori']
            background_path = os.path.join("static", "event_bg", kategori_list[kat_index]['background'])

        kat_counter += 1

        # Draw stretch background
        if os.path.exists(background_path):
            c.drawImage(background_path, x, y, width=tiket_width, height=tiket_height, preserveAspectRatio=False)
        else:
            c.setFillColorRGB(0.95, 0.95, 0.95)
            c.rect(x, y, tiket_width, tiket_height, fill=1)

        # Draw border
        c.setStrokeColorRGB(0, 0, 0)
        c.rect(x, y, tiket_width, tiket_height, stroke=1)

        # Security cut kiri & kanan (15mm)
        cut_width = 15 * mm

        # Rotated text kiri
        c.saveState()
        c.translate(x + 25, y + tiket_height / 2)
        c.rotate(90)
        c.setFont("Helvetica", 6)
        c.drawCentredString(0, 0, f"{kode}")
        c.restoreState()

        # Rotated text kanan
        c.saveState()
        c.translate(x + tiket_width - 25, y + tiket_height / 2)
        c.rotate(-90)
        c.setFont("Helvetica", 6)
        c.drawCentredString(0, 0, f"{kode}")
        c.restoreState()

        # QR Code
        qr = qrcode.make(kode)
        qr_path = f"temp/qr_{kode}.png"
        qr.save(qr_path)
        c.drawImage(qr_path, x + cut_width + 220, y + 11, width=33, height=33)
        os.remove(qr_path)

        # Barcode
        barcode_path = f"temp/barcode_{kode}.png"
        code128 = barcode.get_barcode_class('code128')
        barcode_obj = code128(kode, writer=ImageWriter())
        barcode_obj.save(barcode_path[:-4])
        c.drawImage(barcode_path, x + tiket_width - cut_width - 70, y + 7.5, width=60, height=40)
        os.remove(barcode_path)

        # Teks event & lokasi & tanggal (disesuaikan tengah kiri)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(x + cut_width + 240, y + 45, nama_event)
        c.setFont("Helvetica", 7)
        c.drawCentredString(x + cut_width + 240, y + 7, f"{event['lokasi']} - {event['tanggal']}")

        # Kategori tiket (dekat Kiri)
        c.saveState()
        c.translate(x + 55, y + tiket_height / 2)
        c.rotate(90)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(0, 0, f"{kategori_nama}")
        c.restoreState()

        # Geser ke bawah
        y -= tiket_height + 10
        if y < margin_y:
            c.showPage()
            y = height - tiket_height - margin_y

    c.save()

    buffer.seek(0)

    return send_file(buffer, mimetype='application/pdf')

if __name__ == '__main__':
    app.run(debug=True)