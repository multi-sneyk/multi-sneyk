#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Serwer gry Snake wieloosobowej z użyciem RabbitMQ.
Wykorzystuje dwa oddzielne połączenia:
 - Połączenie do konsumowania (odbiór komunikatów od klientów).
 - Połączenie do publikowania (wysyłanie stanu gry do klientów).

Użytkownik RabbitMQ: adminowiec
Hasło RabbitMQ: Start123!
Host RabbitMQ: localhost (dla serwera Ubuntu w Azure)
Port: 5672 (domyślny)

Autor: ChatGPT
"""

import os
import threading
import time
import json
import pika

# ----- Ustawienia gry -----
UPDATE_INTERVAL = 0.2   # co ile sekund aktualizujemy stan gry
MAX_PLAYERS = 3         # maksymalna liczba graczy

# ----- Pomocnicze stałe -----
WALL = '#'
APPLE = 'O'
EMPTY = '.'

# Kierunki ruchu (vim-style)
DIRECTIONS = {
    'h': (0, -1),  # left
    'l': (0, 1),   # right
    'k': (-1, 0),  # up
    'j': (1, 0)    # down
}


class SnakeGame:
    """
    Klasa zarządzająca logiką gry Snake (wielu graczy, mapy, kolizje).
    """

    def __init__(self, maps_folder="maps"):
        """
        Inicjalizuje stan gry i wczytuje mapy z katalogu `maps_folder`.
        """
        self.maps = {}
        self.load_maps(maps_folder)

        # Domyślny pokój startowy
        self.current_room = "room0"

        # Gracze: {player_id: {positions, direction, alive, room}}
        self.players = {}
        self.player_count = 0

        # Rozmiar mapy (zakładamy, że wszystkie mapy są w tym przykładzie takiej samej wielkości)
        if self.current_room not in self.maps:
            raise ValueError(f"Mapa '{self.current_room}' nie została wczytana.")
        self.height = len(self.maps[self.current_room])
        self.width = len(self.maps[self.current_room][0])

        # Blokada do synchronizacji stanu gry
        self.lock = threading.Lock()

    def load_maps(self, folder):
        """
        Wczytuje pliki .txt z katalogu `folder` do słownika self.maps.
        Klucz: nazwa pliku (bez .txt), wartość: lista wierszy (lista list znaków).
        """
        if not os.path.isdir(folder):
            print(f"[ERROR] Katalog maps '{folder}' nie istnieje.")
            return

        for filename in os.listdir(folder):
            if filename.endswith(".txt"):
                room_name = filename.replace(".txt", "")
                path = os.path.join(folder, filename)
                with open(path, 'r') as f:
                    lines = [list(line.rstrip('\n')) for line in f]
                self.maps[room_name] = lines
                print(f"[INFO] Wczytano mapę '{room_name}' z pliku '{filename}'.")

    def add_player(self, player_id):
        """
        Dodaje nowego gracza do gry (o identyfikatorze `player_id`).
        Zwraca True, jeśli się udało, False w przeciwnym razie.
        """
        with self.lock:
            if self.player_count >= MAX_PLAYERS:
                print(f"[WARN] Osiągnięto limit graczy ({MAX_PLAYERS}). Gracz {player_id} nie został dodany.")
                return False

            # Pozycja startowa (na środku mapy z pewnym przesunięciem)
            start_y = self.height // 2 + self.player_count
            start_x = self.width // 2

            # Upewnij się, że pole jest wolne
            if not self.is_empty_cell(self.current_room, start_y, start_x):
                # Znajdź pierwsze wolne miejsce
                found = False
                for y in range(1, self.height - 1):
                    for x in range(1, self.width - 1):
                        if self.is_empty_cell(self.current_room, y, x):
                            start_y = y
                            start_x = x
                            found = True
                            break
                    if found:
                        break
                if not found:
                    print(f"[ERROR] Brak wolnego miejsca dla nowego gracza {player_id}.")
                    return False

            self.players[player_id] = {
                "positions": [(start_y, start_x)],
                "direction": (0, 0),
                "alive": True,
                "room": self.current_room
            }
            self.player_count += 1
            print(f"[INFO] Dodano gracza {player_id} w pozycji ({start_y}, {start_x}) w pokoju '{self.current_room}'.")
            return True

    def is_empty_cell(self, room_name, y, x):
        """
        Sprawdza, czy na mapie (room_name) w pozycji (y, x) jest puste pole (EMPTY) lub jabłko.
        """
        room_map = self.maps[room_name]
        if room_map[y][x] == WALL:
            return False
        # Jabłko (APPLE) jest uznawane za "puste" pod kątem możliwości wejścia węża
        if room_map[y][x] == APPLE:
            return True
        return (room_map[y][x] == EMPTY or room_map[y][x] == '.')

    def update_player_direction(self, player_id, direction):
        """
        Ustawia nowy kierunek ruchu dla gracza `player_id`.
        """
        with self.lock:
            if player_id in self.players and self.players[player_id]["alive"]:
                if direction in DIRECTIONS:
                    self.players[player_id]["direction"] = DIRECTIONS[direction]
                    print(f"[INFO] Zmieniono kierunek gracza {player_id} na '{direction}'.")
                else:
                    print(f"[WARN] Nieznany kierunek: {direction}")

    def update(self):
        """
        Główna metoda aktualizująca stan gry: przesuwa węże, sprawdza kolizje, itp.
        """
        with self.lock:
            dead_players = []

            for pid, pdata in self.players.items():
                if not pdata["alive"]:
                    continue

                (dy, dx) = pdata["direction"]
                if (dy, dx) == (0, 0):
                    # Jeśli kierunek (0,0), gracz jeszcze nie ruszył
                    continue

                head_y, head_x = pdata["positions"][0]
                new_y = head_y + dy
                new_x = head_x + dx
                current_room = pdata["room"]

                # -- Sprawdź wyjście poza mapę (przejście do sąsiedniego pokoju) --
                if new_y < 0:
                    new_room = self.get_adjacent_room(current_room, "up")
                    if new_room:
                        pdata["room"] = new_room
                        (new_y, new_x) = self.teleport_to_room_edge(new_room, "down", head_x)
                        print(f"[INFO] Gracz {pid} przeszedł do pokoju '{new_room}' od góry.")
                    else:
                        pdata["alive"] = False
                        dead_players.append(pid)
                        print(f"[INFO] Gracz {pid} zderzył się ze ścianą (góra).")
                        continue
                elif new_y >= self.height:
                    new_room = self.get_adjacent_room(current_room, "down")
                    if new_room:
                        pdata["room"] = new_room
                        (new_y, new_x) = self.teleport_to_room_edge(new_room, "up", head_x)
                        print(f"[INFO] Gracz {pid} przeszedł do pokoju '{new_room}' od dołu.")
                    else:
                        pdata["alive"] = False
                        dead_players.append(pid)
                        print(f"[INFO] Gracz {pid} zderzył się ze ścianą (dół).")
                        continue
                elif new_x < 0:
                    new_room = self.get_adjacent_room(current_room, "left")
                    if new_room:
                        pdata["room"] = new_room
                        (new_y, new_x) = self.teleport_to_room_edge(new_room, "right", head_y)
                        print(f"[INFO] Gracz {pid} przeszedł do pokoju '{new_room}' z lewej strony.")
                    else:
                        pdata["alive"] = False
                        dead_players.append(pid)
                        print(f"[INFO] Gracz {pid} zderzył się ze ścianą (lewo).")
                        continue
                elif new_x >= self.width:
                    new_room = self.get_adjacent_room(current_room, "right")
                    if new_room:
                        pdata["room"] = new_room
                        (new_y, new_x) = self.teleport_to_room_edge(new_room, "left", head_y)
                        print(f"[INFO] Gracz {pid} przeszedł do pokoju '{new_room}' z prawej strony.")
                    else:
                        pdata["alive"] = False
                        dead_players.append(pid)
                        print(f"[INFO] Gracz {pid} zderzył się ze ścianą (prawo).")
                        continue

                # -- Mapa w (ewentualnie) nowym pokoju --
                new_room_map = self.maps[pdata["room"]]

                # -- Kolizja ze ścianą --
                if new_room_map[new_y][new_x] == WALL:
                    pdata["alive"] = False
                    dead_players.append(pid)
                    print(f"[INFO] Gracz {pid} zderzył się ze ścianą w pokoju '{pdata['room']}' na pozycji ({new_y}, {new_x}).")
                    continue

                # -- Kolizja z wężami (sobą lub innymi) --
                for other_pid, other_pdata in self.players.items():
                    if not other_pdata["alive"]:
                        continue
                    if other_pid == pid:
                        # kolizja z samym sobą
                        if (new_y, new_x) in other_pdata["positions"]:
                            pdata["alive"] = False
                            dead_players.append(pid)
                            print(f"[INFO] Gracz {pid} zderzył się ze swoim własnym ciałem.")
                            break
                    else:
                        # kolizja z innym graczem
                        if other_pdata["room"] == pdata["room"] and (new_y, new_x) in other_pdata["positions"]:
                            pdata["alive"] = False
                            dead_players.append(pid)
                            print(f"[INFO] Gracz {pid} zderzył się z wężem gracza {other_pid}.")
                            break

                if pid in dead_players:
                    continue

                # -- Ruch węża (przeniesienie głowy) --
                pdata["positions"].insert(0, (new_y, new_x))

                # -- Sprawdź, czy zjadł jabłko (wąż rośnie) --
                if new_room_map[new_y][new_x] == APPLE:
                    new_room_map[new_y][new_x] = EMPTY
                    print(f"[INFO] Gracz {pid} zjadł jabłko na ({new_y}, {new_x}).")
                else:
                    # wąż się nie wydłuża - usuń ogon
                    pdata["positions"].pop()

            # -- Jeśli wszyscy żywi gracze są w tym samym pokoju, aktualizuj self.current_room --
            rooms_used = {self.players[p]["room"] for p in self.players if self.players[p]["alive"]}
            if len(rooms_used) == 1 and len(rooms_used) > 0:
                self.current_room = rooms_used.pop()

    def get_adjacent_room(self, current_room, direction):
        """
        Określa, do którego pokoju trafiamy z current_room w danym kierunku.
        Prosta logika łącząca "room0" i "room1".
        """
        if current_room == "room0":
            if direction == "down":
                return "room1"
            else:
                return None
        elif current_room == "room1":
            if direction == "up":
                return "room0"
            else:
                return None
        return None

    def teleport_to_room_edge(self, new_room, from_direction, coord):
        """
        Teleportuje gracza na krawędź `new_room`.
        from_direction = 'up', 'down', 'left', 'right' (skąd wchodzi).
        coord = x lub y z poprzedniego pokoju.
        Zwraca (new_y, new_x).
        """
        height = len(self.maps[new_room])
        width = len(self.maps[new_room][0])

        if from_direction == "up":
            return (height - 1, coord)  # wchodzi od góry => pojawia się na dole
        elif from_direction == "down":
            return (0, coord)           # od dołu => pojawia się na górze
        elif from_direction == "left":
            return (coord, width - 1)   # z lewej => pojawia się po prawej
        elif from_direction == "right":
            return (coord, 0)           # z prawej => pojawia się po lewej

        # domyślnie środek mapy
        return (height // 2, width // 2)

    def get_game_state(self):
        """
        Zwraca słownik z bieżącym stanem gry (mapy, gracze, aktualny pokój).
        """
        with self.lock:
            state = {
                "current_room": self.current_room,
                "players": {},
                "maps": {}
            }
            # Dodaj reprezentację każdej mapy jako listę stringów
            for rname, rmap in self.maps.items():
                state["maps"][rname] = ["".join(row) for row in rmap]

            # Informacje o każdym graczu
            for pid, pdata in self.players.items():
                state["players"][pid] = {
                    "positions": pdata["positions"],
                    "alive": pdata["alive"],
                    "room": pdata["room"]
                }

            return state


class SnakeServer:
    """
    Serwer, który utrzymuje stan gry i komunikuje się z klientami przez RabbitMQ.
    - Jedno połączenie do start_consuming() (odbieranie).
    - Drugie połączenie do wysyłania aktualizacji stanu gry (publikowanie).
    """

    def __init__(self):
        self.game = SnakeGame()
        self.running = True

        # --- Połączenie do KONSUMOWANIA (odbiór) ---
        try:
            self.consume_connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host='localhost',
                    port=5672,
                    virtual_host='/',
                    credentials=pika.PlainCredentials('adminowiec', '.p=o!v0cD5kK2+F3,{c1&DB')
                )
            )
            self.consume_channel = self.consume_connection.channel()
            self.server_queue = "server_queue"
            self.consume_channel.queue_declare(queue=self.server_queue)
            self.consume_channel.basic_qos(prefetch_count=1)
            self.consume_channel.basic_consume(
                queue=self.server_queue,
                on_message_callback=self.on_request,
                auto_ack=True
            )
            print("[SERVER] Połączenie do konsumowania utworzone.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] Nie udało się połączyć z RabbitMQ do konsumowania: {e}")
            self.running = False

        # --- Połączenie do PUBLIKOWANIA (wysyłanie stanu gry) ---
        try:
            self.publish_connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host='localhost',
                    port=5672,
                    virtual_host='/',
                    credentials=pika.PlainCredentials('adminowiec', '.p=o!v0cD5kK2+F3,{c1&DB')
                )
            )
            self.publish_channel = self.publish_connection.channel()
            self.game_state_exchange = "game_state_exchange"
            self.publish_channel.exchange_declare(
                exchange=self.game_state_exchange,
                exchange_type='fanout'
            )
            print("[SERVER] Połączenie do publikowania utworzone.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] Nie udało się połączyć z RabbitMQ do publikowania: {e}")
            self.running = False

        # Uruchamiamy wątek głównej pętli gry
        if self.running:
            self.update_thread = threading.Thread(target=self.game_loop, daemon=True)
            self.update_thread.start()
            print("[SERVER] Wątek game_loop uruchomiony.")

    def on_request(self, ch, method, props, body):
        """
        Callback wywoływany po odebraniu wiadomości od klienta.
        """
        try:
            message = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            print("[WARN] Otrzymano niepoprawny JSON.")
            return

        msg_type = message.get("type", "")
        if msg_type == "join_game":
            player_id = str(message.get("player_id"))
            if player_id:
                success = self.game.add_player(player_id)
                if success:
                    print(f"[SERVER] Gracz {player_id} dołączył do gry.")
                else:
                    print(f"[SERVER] Gracz {player_id} NIE dołączył (limit lub brak miejsca).")
        elif msg_type == "player_move":
            player_id = str(message.get("player_id"))
            direction = message.get("direction")
            if player_id and direction:
                self.game.update_player_direction(player_id, direction)
                print(f"[SERVER] Gracz {player_id} zmienił kierunek na '{direction}'.")
        else:
            print(f"[WARN] Nieznany typ wiadomości: {msg_type}")

    def game_loop(self):
        """
        Wątek: wykonuje pętlę aktualizacji stanu gry i rozsyła go do klientów.
        """
        while self.running:
            self.game.update()
            state = self.game.get_game_state()
            # Publikacja stanu gry do wymiany fanout
            try:
                self.publish_channel.basic_publish(
                    exchange=self.game_state_exchange,
                    routing_key='',
                    body=json.dumps(state)
                )
            except pika.exceptions.AMQPError as e:
                print(f"[ERROR] Błąd podczas publikowania stanu gry: {e}")
                self.running = False

            time.sleep(UPDATE_INTERVAL)

    def start_server(self):
        """
        Główna metoda, która wywołuje start_consuming() (blokująco).
        """
        if not self.running:
            print("[SERVER] Serwer nie został poprawnie zainicjalizowany. Zamykanie.")
            return

        print("[SERVER] Serwer wystartował. Oczekiwanie na klientów...")
        try:
            self.consume_channel.start_consuming()
        except KeyboardInterrupt:
            print("\n[SERVER] Przerwano serwer (Ctrl+C).")
        finally:
            self.running = False
            try:
                self.consume_channel.stop_consuming()
            except:
                pass

            if hasattr(self, 'update_thread') and self.update_thread.is_alive():
                self.update_thread.join()

            try:
                self.consume_connection.close()
            except:
                pass

            try:
                self.publish_connection.close()
            except:
                pass

            print("[SERVER] Serwer zamknięty.")


if __name__ == "__main__":
    server = SnakeServer()
    server.start_server()
