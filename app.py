from __future__ import annotations

from repatriants_app import create_app
from repatriants_app.extensions import db


app = create_app()


if __name__ == "__main__":
    import socket
    import sys

    def get_local_ip():
        """Получает локальный IP-адрес"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception:
            return "127.0.0.1"

    # Проверяем аргументы командной строки
    if len(sys.argv) > 1 and sys.argv[1] == "--local":
        # Запуск для локальной сети с подробной информацией
        local_ip = get_local_ip()
        port = 5000

        print("=" * 60)
        print("🚀 ЗАПУСК СИСТЕМЫ РЕПАТРИАНТОВ В ЛОКАЛЬНОЙ СЕТИ")
        print("=" * 60)
        print(f"🌐 Локальный IP: {local_ip}")
        print(f"🔌 Порт: {port}")
        print()
        print("🌍 ДОСТУП К ПРИЛОЖЕНИЮ:")
        print(f"💻 Локально:     http://localhost:{port}")
        print(f"🏠 Локальная сеть: http://{local_ip}:{port}")
        print()
        print("📱 ДЛЯ ДРУГИХ УСТРОЙСТВ В СЕТИ:")
        print("1. Убедитесь, что устройство подключено к той же сети")
        print("2. Откройте браузер и перейдите по адресу:")
        print(f"   http://{local_ip}:{port}")
        print("=" * 60)

        with app.app_context():
            db.create_all()
        app.run(debug=True, host="0.0.0.0", port=port, threaded=True)
    else:
        # Обычный запуск с отображением локального IP
        local_ip = get_local_ip()
        port = 5000

        print("=" * 60)
        print("🚀 СИСТЕМА РЕПАТРИАНТОВ")
        print("=" * 60)
        print(f"🌐 Локальный IP: {local_ip}")
        print(f"🔌 Порт: {port}")
        print()
        print("🌍 ДОСТУП К ПРИЛОЖЕНИЮ:")
        print(f"💻 Локально:     http://localhost:{port}")
        print(f"🏠 Локальная сеть: http://{local_ip}:{port}")
        print("=" * 60)

        with app.app_context():
            db.create_all()
        app.run(debug=True, host="0.0.0.0", port=port, threaded=True)
