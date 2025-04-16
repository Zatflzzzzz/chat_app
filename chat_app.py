import socket
import threading
import argparse
import sys
import errno
from ipaddress import ip_address, ip_network

class PortChecker:
    _used_ports = set()

    @classmethod
    def is_port_available(cls, port):
        """Проверяет, свободен ли порт для любого протокола"""
        if port in cls._used_ports:
            return False

        # Проверяем порт для TCP
        try:
            tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            tcp_socket.bind(('0.0.0.0', port))
            tcp_socket.close()
        except socket.error:
            return False

        # Проверяем порт для UDP
        try:
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            udp_socket.bind(('0.0.0.0', port))
            udp_socket.close()
        except socket.error:
            return False

        cls._used_ports.add(port)
        return True

    @classmethod
    def release_port(cls, port):
        """Освобождает порт"""
        cls._used_ports.discard(port)

class ChatServer:
    def __init__(self, host, port, protocol='TCP'):
        self.host = host if host != '0.0.0.0' else socket.gethostbyname(socket.gethostname())
        self.port = port
        self.protocol = protocol.upper()
        self.clients = []
        self.server_socket = None
        self.running = False
        self.lock = threading.Lock()
        
    def start(self):
        """Запускает сервер с проверкой порта"""
        if not PortChecker.is_port_available(self.port):
            print(f"Порт {self.port} уже занят!")
            return False
            
        try:
            if self.protocol == 'TCP':
                self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.server_socket.bind((self.host, self.port))
                self.server_socket.listen(5)
                print(f"TCP сервер запущен на {self.host}:{self.port}")
            else:
                self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.server_socket.bind((self.host, self.port))
                print(f"UDP сервер запущен на {self.host}:{self.port}")
            
            self.running = True
            threading.Thread(target=self.accept_connections, daemon=True).start()
            return True
        except Exception as e:
            print(f"Ошибка запуска сервера: {e}")
            PortChecker.release_port(self.port)
            return False
    
    def accept_connections(self):
        """Принимает входящие подключения"""
        while self.running:
            try:
                if self.protocol == 'TCP':
                    client_socket, addr = self.server_socket.accept()
                    print(f"Новое подключение от {addr}")
                    with self.lock:
                        self.clients.append((client_socket, addr))
                    threading.Thread(target=self.handle_tcp_client, args=(client_socket, addr), daemon=True).start()
                else:
                    data, addr = self.server_socket.recvfrom(1024)
                    with self.lock:
                        if addr not in [c[1] for c in self.clients]:
                            print(f"Новое UDP подключение от {addr}")
                            self.clients.append((None, addr))
                    self.broadcast(data, addr)
            except Exception as e:
                if self.running:
                    print(f"Ошибка при принятии подключения: {e}")
                break
    
    def handle_tcp_client(self, client_socket, addr):
        """Обрабатывает сообщения от TCP клиента"""
        while self.running:
            try:
                data = client_socket.recv(1024)
                if not data:
                    print(f"Клиент {addr} отключился")
                    break
                print(f"[TCP] Получено от {addr}: {data.decode()}")
                self.broadcast(data, addr)
            except ConnectionResetError:
                print(f"Клиент {addr} разорвал соединение")
                break
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Ошибка при работе с клиентом {addr}: {e}")
                break
        
        with self.lock:
            self.remove_client(addr)
        client_socket.close()
    
    def broadcast(self, data, sender_addr):
        """Отправляет сообщение всем подключенным клиентам"""
        message = f"{sender_addr}: {data.decode()}"
        print(f"[{self.protocol}] Отправка: {message}", end='')
        
        with self.lock:
            clients = self.clients.copy()
        
        for client in clients:
            addr = client[1]
            if addr != sender_addr:
                try:
                    if self.protocol == 'TCP':
                        client[0].sendall(data)
                        print(f"[TCP] Отправлено {addr}: {data.decode()}")
                    else:
                        self.server_socket.sendto(data, addr)
                        print(f"[UDP] Отправлено {addr}: {data.decode()}")
                except ConnectionResetError:
                    print(f"Клиент {addr} отключился при отправке")
                    self.remove_client(addr)
                except Exception as e:
                    print(f"Ошибка при отправке сообщения клиенту {addr}: {e}")
                    self.remove_client(addr)
    
    def remove_client(self, addr):
        """Удаляет клиента из списка подключенных"""
        self.clients = [c for c in self.clients if c[1] != addr]
    
    def stop(self):
        """Останавливает сервер и освобождает порт"""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        with self.lock:
            for client in self.clients:
                if client[0]:
                    client[0].close()
            self.clients = []
        PortChecker.release_port(self.port)
        print("Сервер остановлен")

class ChatClient:
    def __init__(self, protocol='TCP'):
        self.protocol = protocol.upper()
        self.socket = None
        self.running = False
        self.server_address = None
        self.lock = threading.Lock()
    
    def is_server_available(self, host, port):
        """Проверяет, доступен ли сервер"""
        try:
            test_socket = socket.socket(socket.AF_INET, 
                                     socket.SOCK_STREAM if self.protocol == 'TCP' else socket.SOCK_DGRAM)
            test_socket.settimeout(2)
            
            if self.protocol == 'TCP':
                test_socket.connect((host, port))
            else:
                test_socket.bind(('', 0))
                test_socket.sendto(b'ping', (host, port))
                try:
                    test_socket.recvfrom(1024)
                except socket.timeout:
                    pass
            
            test_socket.close()
            return True
        except Exception as e:
            print(f"\nОшибка проверки сервера: {e}")
            return False
    
    def connect(self, host, port):
        """Подключается к серверу"""
        if not self.is_server_available(host, port):
            print(f"\nСервер {host}:{port} недоступен!")
            return False
            
        try:
            self.server_address = (host, port)
            
            if self.protocol == 'TCP':
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(0.5)
                self.socket.connect((host, port))
                print(f"\nПодключено к TCP серверу {host}:{port}")
            else:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                # Для UDP явно биндим сокет к конкретному интерфейсу
                local_ip = socket.gethostbyname(socket.gethostname())
                self.socket.bind((local_ip, 0))  # Используем случайный порт для клиента
                print(f"\nПодключено к UDP серверу {host}:{port} с локального адреса {local_ip}")
            
            self.running = True
            threading.Thread(target=self.receive_messages, daemon=True).start()
            return True
        except Exception as e:
            print(f"\nОшибка подключения: {e}")
            return False
    
    def receive_messages(self):
        """Получает сообщения от сервера"""
        while self.running:
            try:
                if self.protocol == 'TCP':
                    try:
                        data = self.socket.recv(1024)
                        if not data:
                            print("\nСервер отключился")
                            break
                        print(f"\n[TCP] Получено: {data.decode()}\n> ", end='')
                    except socket.timeout:
                        continue
                else:
                    data, addr = self.socket.recvfrom(1024)
                    print(f"\n[UDP] Получено от {addr}: {data.decode()}\n> ", end='')
                    
            except ConnectionResetError:
                print("\nСервер принудительно разорвал соединение")
                break
            except OSError as e:
                if e.errno == errno.WSAECONNRESET:
                    print("\nСоединение было сброшено сервером")
                else:
                    print(f"\nОшибка соединения: {e}")
                break
            except Exception as e:
                if self.running:
                    print(f"\nНеизвестная ошибка: {e}")
                break
        
        self.disconnect()
    
    def send_message(self, message):
        """Отправляет сообщение на сервер"""
        if not self.running or not self.socket:
            print("\nНет подключения к серверу")
            return False
        
        try:
            if self.protocol == 'TCP':
                self.socket.sendall(message.encode())
                print(f"[TCP] Отправлено: {message}")
            else:
                self.socket.sendto(message.encode(), self.server_address)
                print(f"[UDP] Отправлено: {message}")
            return True
        except Exception as e:
            print(f"\nОшибка отправки: {e}")
            return False
    
    def disconnect(self):
        """Отключается от сервера"""
        if not self.running:
            return
            
        self.running = False
        if self.socket:
            try:
                if self.protocol == 'TCP':
                    self.socket.shutdown(socket.SHUT_RDWR)
                self.socket.close()
            except:
                pass
        self.socket = None
        print("\nОтключено от сервера")

def run_server(host, port, protocol):
    """Запускает сервер чата"""
    server = ChatServer(host, port, protocol)
    if not server.start():
        sys.exit(1)
        
    try:
        while True:
            cmd = input("Введите 'stop' для остановки сервера: ")
            if cmd.lower() == 'stop':
                break
    except KeyboardInterrupt:
        print("\nЗавершение работы сервера...")
    finally:
        server.stop()

def run_client(host, port, protocol):
    """Запускает клиент чата"""
    client = ChatClient(protocol)
    if not client.connect(host, port):
        sys.exit(1)
    
    try:
        while client.running:
            try:
                message = input("> ")
                if message.lower() == 'exit':
                    break
                if not client.send_message(message):
                    break
            except KeyboardInterrupt:
                print("\nЗавершение работы клиента...")
                break
            except Exception as e:
                print(f"\nОшибка ввода: {e}")
                break
    finally:
        client.disconnect()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Чат-приложение')
    subparsers = parser.add_subparsers(dest='command', help='Команда', required=True)

    # Парсер для сервера
    server_parser = subparsers.add_parser('server', help='Запуск сервера')
    server_parser.add_argument('--host', default='0.0.0.0', help='IP адрес сервера')
    server_parser.add_argument('--port', type=int, required=True, help='Порт сервера')
    server_parser.add_argument('--protocol', choices=['TCP', 'UDP'], default='TCP', help='Протокол (TCP/UDP)')

    # Парсер для клиента
    client_parser = subparsers.add_parser('client', help='Запуск клиента')
    client_parser.add_argument('--host', required=True, help='IP адрес сервера')
    client_parser.add_argument('--port', type=int, required=True, help='Порт сервера')
    client_parser.add_argument('--protocol', choices=['TCP', 'UDP'], default='TCP', help='Протокол (TCP/UDP)')

    args = parser.parse_args()

    try:
        if args.command == 'server':
            run_server(args.host, args.port, args.protocol)
        elif args.command == 'client':
            run_client(args.host, args.port, args.protocol)
    except KeyboardInterrupt:
        print("\nПриложение завершено пользователем")
    except Exception as e:
        print(f"\nКритическая ошибка: {e}")