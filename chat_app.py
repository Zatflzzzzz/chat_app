import socket
import threading
import json
import time
from datetime import datetime


def _is_port_in_use(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.connect((host, port))
            return True  # Порт занят
        except (ConnectionRefusedError, OSError):
            return False  # Порт свободен


class ChatApplication:
    def __init__(self):
        self.server_socket = None
        self.client_socket = None
        self.clients = []
        self.running = False
        self.username = ""
        self.message_id = 0

    def run_server(self):
        print("\nНастройка сервера:")
        host = self._get_input("Введите IP адрес сервера", "127.0.0.1")
        port = self._get_number_input("Введите порт сервера", 5555)
        protocol = self._get_input("Выберите протокол (TCP/UDP)", "TCP").upper()

        if protocol not in ["TCP", "UDP"]:
            print("Неверный протокол. Используется TCP по умолчанию")
            protocol = "TCP"

        try:
            if _is_port_in_use(host, port):
                print(f"\n[ОШИБКА] Порт {port} уже используется. Выберите другой порт.")
                return

            if protocol == "TCP":
                self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.server_socket.bind((host, port))
                self.server_socket.listen(5)
            else:
                self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.server_socket.bind((host, port))

            self.running = True

            print("\n" + "=" * 50)
            print(f"Сервер запущен на {host}:{port} ({protocol})")
            print(f"Введите 'stop' для остановки сервера")
            print("=" * 50 + "\n")

            if protocol == "TCP":
                threading.Thread(target=self._accept_tcp_connections, daemon=True).start()
            else:
                threading.Thread(target=self._handle_udp_connections, daemon=True).start()

            while self.running:
                cmd = input("> ")
                if cmd.lower() == 'stop':
                    break

        except Exception as e:
            print(f"\n[ОШИБКА] Не удалось запустить сервер: {e}")
        finally:
            self._stop_server()

    def run_client(self):
        print("\nНастройка клиента:")
        client_host = self._get_input("Введите ваш IP адрес", "127.0.0.1")
        server_host = self._get_input("Введите IP адрес сервера", "127.0.0.1")
        server_port = self._get_number_input("Введите порт сервера", 5555)
        protocol = self._get_input("Выберите протокол (TCP/UDP)", "TCP").upper()
        self.username = self._get_input("Введите ваше имя")

        if protocol not in ["TCP", "UDP"]:
            print("Неверный протокол. Используется TCP по умолчанию")
            protocol = "TCP"

        try:
            if protocol == "TCP":
                self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.client_socket.bind((client_host, 0))  # Случайный порт
                try:
                    self.client_socket.connect((server_host, server_port))
                except ConnectionRefusedError:
                    raise Exception("Не удалось подключиться. Проверьте порт или IP-адрес сервера")
                except socket.timeout:
                    raise Exception("Таймаут подключения. Проверьте порт или IP-адрес сервера")

                # Регистрация клиента
                self._send_data({
                    "type": "register",
                    "name": self.username
                })
            else:
                self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.client_socket.bind((client_host, 0))
                self._send_data({
                    "type": "register",
                    "name": self.username
                }, (server_host, server_port))

            self.running = True

            print("\n" + "=" * 50)
            print(f"Подключено к серверу {server_host}:{server_port} ({protocol})")
            print(f"Ваше имя: {self.username}")
            print(f"Введите сообщение или 'exit' для выхода")
            print("=" * 50 + "\n")

            threading.Thread(target=self._receive_messages, daemon=True).start()

            while self.running:
                message = input("> ")
                if message.lower() == 'exit':
                    break

                self._send_data({
                    "type": "message",
                    "text": message,
                    "sender": self.username,
                    "time": time.time()
                }, (server_host, server_port) if protocol == "UDP" else None)

        except Exception as e:
            print(f"\n[ОШИБКА] {e}")
        finally:
            self._disconnect_client()

    def _accept_tcp_connections(self):
        while self.running:
            try:
                client_socket, addr = self.server_socket.accept()

                # Получаем имя клиента
                data = self._receive_data(client_socket)
                if data and data.get("type") == "register":
                    username = data.get("name", f"Клиент_{addr[1]}")

                client_info = {
                    "socket": client_socket,
                    "address": addr,
                    "username": username
                }

                self.clients.append(client_info)
                print(f"[ПОДКЛЮЧЕНИЕ] {username} ({addr[0]}:{addr[1]})")

                self._broadcast({
                    "type": "system",
                    "text": f"{username} присоединился к чату",
                    "time": time.time()
                }, exclude=client_socket)

                threading.Thread(
                    target=self._handle_tcp_client,
                    args=(client_info,),
                    daemon=True
                ).start()

            except Exception as e:
                if self.running:
                    print(f"[ОШИБКА] Ошибка подключения: {e}")

    def _handle_udp_connections(self):
        while self.running:
            try:
                data, addr = self.server_socket.recvfrom(4096)
                data = json.loads(data.decode())

                if data.get("type") == "register":
                    # Новый клиент
                    username = data.get("name", f"Клиент_{addr[1]}")
                    client_info = {
                        "address": addr,
                        "username": username
                    }
                    self.clients.append(client_info)
                    print(f"[ПОДКЛЮЧЕНИЕ] {username} ({addr[0]}:{addr[1]})")

                    self._broadcast({
                        "type": "system",
                        "text": f"{username} присоединился к чату",
                        "time": time.time()
                    }, exclude=addr)

                elif data.get("type") == "message":
                    # Пересылаем сообщение всем
                    self._broadcast({
                        "type": "message",
                        "text": data["text"],
                        "sender": next(
                            (c["username"] for c in self.clients if c["address"] == addr),
                            "Неизвестный"),
                        "time": data.get("time", time.time())
                    }, exclude=addr)

            except Exception as e:
                if self.running:
                    print(f"[ОШИБКА] Ошибка обработки UDP: {e}")

    def _handle_tcp_client(self, client_info):
        while self.running:
            try:
                data = self._receive_data(client_info["socket"])
                if not data:
                    break

                if data.get("type") == "message":
                    print(f"[{datetime.fromtimestamp(data['time']).strftime('%H:%M:%S')}] "
                          f"{client_info['username']}: {data['text']}")

                    self._broadcast({
                        "type": "message",
                        "text": data["text"],
                        "sender": client_info["username"],
                        "time": data["time"]
                    }, exclude=client_info["socket"])

            except Exception as e:
                if self.running:
                    print(f"[ОШИБКА] Ошибка клиента: {e}")
                break

        self._remove_client(client_info)
        print(f"[ОТКЛЮЧЕНИЕ] {client_info['username']} ({client_info['address'][0]}:{client_info['address'][1]})")
        self._broadcast({
            "type": "system",
            "text": f"{client_info['username']} покинул чат",
            "time": time.time()
        })

    def _receive_messages(self):
        while self.running:
            try:
                data = self._receive_data()
                if not data:
                    print("[СЕРВЕР] Соединение разорвано")
                    self.running = False
                    break

                if data.get("type") == "system":
                    print(f"[СИСТЕМА] {data['text']}")
                elif data.get("type") == "message":
                    print(f"[{datetime.fromtimestamp(data['time']).strftime('%H:%M:%S')}] "
                          f"{data.get('sender', 'Неизвестный')}: {data['text']}")

            except Exception as e:
                if self.running:
                    print(f"[ОШИБКА] Ошибка получения: {e}")
                    self.running = False
                break

    def _send_data(self, data, addr=None):
        try:
            if addr:  # Для UDP
                self.client_socket.sendto((json.dumps(data) + "\n").encode(), addr)
            else:  # Для TCP
                self.client_socket.sendall((json.dumps(data) + "\n").encode())
        except Exception as e:
            raise Exception(f"Ошибка отправки: {e}")

    def _receive_data(self, sock=None):
        sock = sock or self.client_socket
        try:
            if isinstance(sock, socket.socket) and sock.type == socket.SOCK_STREAM:
                data = sock.recv(4096).decode()
                return json.loads(data.strip()) if data.strip() else None
            elif isinstance(sock, socket.socket) and sock.type == socket.SOCK_DGRAM:
                data, _ = sock.recvfrom(4096)
                return json.loads(data.decode().strip()) if data.strip() else None
        except Exception as e:
            raise Exception(f"Ошибка получения: {e}")

    def _broadcast(self, data, exclude=None):
        self.message_id += 1
        data["id"] = self.message_id

        for client in self.clients.copy():
            try:
                if isinstance(exclude, socket.socket) and "socket" in client and client["socket"] != exclude:
                    client["socket"].sendall((json.dumps(data) + "\n").encode())
                elif isinstance(exclude, tuple) and "address" in client and client["address"] != exclude:
                    self.server_socket.sendto((json.dumps(data) + "\n").encode(), client["address"])
                elif exclude is None:
                    if "socket" in client:
                        client["socket"].sendall((json.dumps(data) + "\n").encode())
                    elif "address" in client:
                        self.server_socket.sendto((json.dumps(data) + "\n").encode(), client["address"])
            except:
                self._remove_client(client)

    def _remove_client(self, client_info):
        if client_info in self.clients:
            if "socket" in client_info:
                try:
                    client_info["socket"].close()
                except:
                    pass
            self.clients.remove(client_info)

    def _stop_server(self):
        self.running = False
        for client in self.clients:
            try:
                if "socket" in client:
                    client["socket"].close()
            except:
                pass
        self.clients.clear()
        if self.server_socket:
            self.server_socket.close()
        print("\nСервер остановлен")

    def _disconnect_client(self):
        self.running = False
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass
        print("\nОтключено от сервера")

    def _get_input(self, prompt, default=None):
        user_input = input(f"{prompt} [{default}]: " if default else f"{prompt}: ").strip()
        return user_input if user_input else default

    def _get_number_input(self, prompt, default=None):
        while True:
            try:
                value = input(f"{prompt} [{default}]: " if default else f"{prompt}: ").strip()
                return int(value or default)
            except ValueError:
                print("Пожалуйста, введите число")


if __name__ == "__main__":
    print("=" * 50)
    print("Чат-приложение")
    print("1. Запустить сервер")
    print("2. Запустить клиент")
    print("=" * 50)

    app = ChatApplication()

    while True:
        choice = input("Выберите действие (1/2): ")
        if choice == '1':
            app.run_server()
            break
        elif choice == '2':
            app.run_client()
            break
        else:
            print("Неверный выбор")