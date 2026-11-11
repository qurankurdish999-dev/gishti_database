"""
داتابەیسی گشتی — دەستپێکەری دێسکتۆپ
=========================================
ئەم فایلە بەرنامەکە دەکاتە پەنجەرەیەکی ڕاستەقینەی دێسکتۆپ (نەک لاپەڕەی وێبگەڕ).
Flask لە باکگراوندا کاردەکات و پەنجەرەیەکی native (بە pywebview) بۆی دەکرێتەوە.

بۆ کارپێکردن ڕاستەوخۆ:
    python desktop_app.py

بۆ دروستکردنی .exe، سەیری فایلی README.md بکە (بەشی "دروستکردنی exe").
"""
import threading
import webview

from app import app, init_db

HOST = "127.0.0.1"
PORT = 5000


def start_flask():
    # use_reloader=False گرنگە، چونکە لە thread دا کاردەکات
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=True)


def main():
    init_db()

    server_thread = threading.Thread(target=start_flask, daemon=True)
    server_thread.start()

    webview.create_window(
        title="داتابەیسی گشتی — سیستەمی بەڕێوەبردنی فرۆشتن و کۆگا",
        url=f"http://{HOST}:{PORT}",
        width=1300,
        height=850,
        min_size=(1000, 650),
        text_select=True,
    )
    webview.start()


if __name__ == "__main__":
    main()
