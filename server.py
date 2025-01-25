#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Serwer gry Snake wieloosobowej z użyciem RabbitMQ.
Nowe wymagania:
- Możliwość restartu gry klawiszem 'r' (od dowolnego gracza).
- Węże faktycznie rosną po zjedzeniu jabłka.
- Większe mapy (20x40).
- Gracze startują w samym środku, ale w różnych kolumnach.

Użytkownik RabbitMQ: adminowiec
Hasło RabbitMQ: .p=o!v0cD5kK2+F3,{c1&DB
"""

import os
import threading
import time
import json
import random
import pika

# ----- Ustawienia gry -----
UPDATE_INTERVAL = 0.2  # co ile sekund aktualizujemy stan gry
MAX_PLAYERS = 6        # maksymalna liczba graczy

# ----- Pomocnicze stałe -----
WALL = '#'
APPLE = 'O'
EMPTY = '.'

# Kierunki ruchu (vim-style)
DIRECTIONS = {
    'h': (0, -1),   # left
    'l': (0, 1),    # right
    'k': (-1, 0),   # up
    'j': (1, 0)     # down
}


class SnakeGame:
    """
    Główna klasa logiki gry. Przechowuje mapy, graczy, obsługuje ruch, kolizje, jabłka itd.
    """

    def __init__(self, maps_folder="maps"):
        self.maps = {}
        self.load_maps(maps_folder)

        self.current_room = "room0"
        self.players = {}
        self.player_count = 0

        if self.current_room not in self.maps:
            raise ValueError(f"Mapa '{self.current_room}' nie została wczytana.")
        self.height = len(self.maps[self.current_room])
        self.width = len(self.maps[self.current_room][0])

        self.lock = threading.Lock()

        # Przygotuj listę punktów startowych.
        # Gracze wystartują w jednym rzędzie (center_row) ale w różnych kolumnach wokół środka.
        self.start_positions = self.generate_start_positions()

    def load_maps(self, folder):
        """
        Wczytuje pliki tekstowe z katalogu `folder` (np. room0.txt, room1.txt).
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

    def generate_start_positions(self):
        """
        Generuje listę pozycji startowych w samym środku w linii poziomej.
        Np. dla 6 graczy: [ (row, midX-2), (row, midX-1), (row, midX), (row, midX+1), ... ]
        """
        center_row = self.height // 2
        center_col = self.width // 2
        offset_list = [-2, -1, 0, 1, 2, 3]  # tyle, ile MAX_PLAYERS
        positions = []
        for offset in offset_list:
            y = center_row
            x = center_col + offset
            positions.append((self.current_room, y, x))
        return positions

    def add_player(self, player_id):
        """
        Dodaje nowego gracza do gry, ustawia mu pozycję i podstawowe parametry.
        """
        with self.lock:
            if self.player_count >= MAX_PLAYERS:
                print(f"[WARN] Osiągnięto limit graczy ({MAX_PLAYERS}). Gracz {player_id} nie został dodany.")
                return False

            # Wybierz startową z listy
            if self.player_count < len(self.start_positions):
                (room, sy, sx) = self.start_positions[self.player_count]
            else:
                # awaryjnie środek mapy
                room = self.current_room
                sy = self.height // 2
                sx = self.width // 2

            if not self.is_empty_cell(room, sy, sx):
                # jeśli jednak kolizja, poszukaj wolnego pola
                found = False
                for y in range(1, self.height - 1):
                    for x in range(1, self.width - 1):
                        if self.is_empty_cell(room, y, x):
                            sy, sx = y, x
                            found = True
                            break
                    if found:
                        break
                if not found:
                    print(f"[ERROR] Brak wolnego miejsca dla nowego gracza {player_id}.")
                    return False

            self.players[player_id] = {
                "positions": [(sy, sx)],
                "direction": (0, 0),
                "alive": True,
                "room": room
            }
            self.player_count += 1
            print(f"[INFO] Dodano gracza {player_id} w pozycji ({sy}, {sx}) w pokoju '{room}'.")
            return True

    def is_empty_cell(self, room_name, y, x):
        """
        Czy komórka (y, x) jest wolna (pusta lub jabłko).
        """
        room_map = self.maps[room_name]
        cell = room_map[y][x]
        if cell == WALL:
            return False
        # APPLE też dozwolone
        return True

    def update_player_direction(self, player_id, direction):
        """
        Ustaw nowy kierunek ruchu (vim: h, j, k, l).
        """
        with self.lock:
            if player_id in self.players and self.players[player_id]["alive"]:
                if direction in DIRECTIONS:
                    self.players[player_id]["direction"] = DIRECTIONS[direction]

    def update(self):
        """
        Główna metoda: przesuwa węże, sprawdza kolizje, węże rosną po zjedzeniu jabłka, jabłka się respawnują.
        """
        with self.lock:
            dead_players = []

            for pid, pdata in self.players.items():
                if not pdata["alive"]:
                    continue

                (dy, dx) = pdata["direction"]
                if (dy, dx) == (0, 0):
                    # gracz jeszcze nie ruszył
                    continue

                head_y, head_x = pdata["positions"][0]
                new_y = head_y + dy
                new_x = head_x + dx
                current_room = pdata["room"]

                # -- Wyjście poza mapę => inny pokój lub kolizja --
                if new_y < 0:
                    new_room = self.get_adjacent_room(current_room, "up")
                    if new_room:
                        pdata["room"] = new_room
                        (new_y, new_x) = self.teleport_to_room_edge(new_room, "down", head_x)
                    else:
                        pdata["alive"] = False
                        dead_players.append(pid)
                        continue
                elif new_y >= self.height:
                    new_room = self.get_adjacent_room(current_room, "down")
                    if new_room:
                        pdata["room"] = new_room
                        (new_y, new_x) = self.teleport_to_room_edge(new_room, "up", head_x)
                    else:
                        pdata["alive"] = False
                        dead_players.append(pid)
                        continue
                elif new_x < 0:
                    new_room = self.get_adjacent_room(current_room, "left")
                    if new_room:
                        pdata["room"] = new_room
                        (new_y, new_x) = self.teleport_to_room_edge(new_room, "right", head_y)
                    else:
                        pdata["alive"] = False
                        dead_players.append(pid)
                        continue
                elif new_x >= self.width:
                    new_room = self.get_adjacent_room(current_room, "right")
                    if new_room:
                        pdata["room"] = new_room
                        (new_y, new_x) = self.teleport_to_room_edge(new_room, "left", head_y)
                    else:
                        pdata["alive"] = False
                        dead_players.append(pid)
                        continue

                room_map = self.maps[pdata["room"]]

                # Kolizja ze ścianą
                if room_map[new_y][new_x] == WALL:
                    pdata["alive"] = False
                    dead_players.append(pid)
                    continue

                # Kolizje z wężami
                for other_pid, other_pdata in self.players.items():
                    if not other_pdata["alive"]:
                        continue
                    if other_pid == pid:
                        # z samym sobą
                        if (new_y, new_x) in other_pdata["positions"]:
                            pdata["alive"] = False
                            dead_players.append(pid)
                            break
                    else:
                        # z innym graczem
                        if other_pdata["room"] == pdata["room"] and (new_y, new_x) in other_pdata["positions"]:
                            pdata["alive"] = False
                            dead_players.append(pid)
                            break

                if pid in dead_players:
                    continue

                # Ruch węża: dodaj głowę
                pdata["positions"].insert(0, (new_y, new_x))

                # Sprawdź, czy zjadł jabłko
                if room_map[new_y][new_x] == APPLE:
                    room_map[new_y][new_x] = EMPTY
                    print(f"[INFO] Gracz {pid} zjadł jabłko => wąż się wydłuża")
                    # w tym miejscu ogon NIE jest usuwany => wąż rośnie
                    self.spawn_random_apple(pdata["room"])
                else:
                    # Normalny ruch => usuń ogon
                    pdata["positions"].pop()

            # Jeśli wszyscy żywi gracze w tym samym pokoju => current_room = ...
            rooms_used = {self.players[p]["room"] for p in self.players if self.players[p]["alive"]}
            if len(rooms_used) == 1 and len(rooms_used) > 0:
                self.current_room = rooms_used.pop()

    def spawn_random_apple(self, room_name):
        """
        Dodaje jabłko w losowym, wolnym miejscu mapy (gdzie nie ma węży i nie ma ścian).
        """
        room_map = self.maps[room_name]
        empty_positions = []
        for y in range(1, self.height - 1):
            for x in range(1, self.width - 1):
                if room_map[y][x] == EMPTY or room_map[y][x] == '.':
                    # sprawdź, czy nie ma tam ciała węża
                    if not self.is_snake_on_cell(room_name, y, x):
                        empty_positions.append((y, x))

        if not empty_positions:
            print("[WARN] Brak wolnych pozycji na jabłko.")
            return

        (rand_y, rand_x) = random.choice(empty_positions)
        room_map[rand_y][rand_x] = APPLE
        print(f"[INFO] Nowe jabłko w pokoju={room_name}, y={rand_y}, x={rand_x}.")

    def is_snake_on_cell(self, room_name, y, x):
        for pid, pdata in self.players.items():
            if not pdata["alive"]:
                continue
            if pdata["room"] == room_name and (y, x) in pdata["positions"]:
                return True
        return False

    def get_adjacent_room(self, current_room, direction):
        """
        Prosta logika łącząca room0 -> room1 itp.
        """
        if current_room == "room0":
            if direction == "down":
                return "room1"
            return None
        elif current_room == "room1":
            if direction == "up":
                return "room0"
            return None
        return None

    def teleport_to_room_edge(self, new_room, from_direction, coord):
        """
        Ustawia gracza na krawędź new_room w zależności od from_direction.
        """
        height = len(self.maps[new_room])
        width = len(self.maps[new_room][0])

        if from_direction == "up":
            return (height - 1, coord)
        elif from_direction == "down":
            return (0, coord)
        elif from_direction == "left":
            return (coord, width - 1)
        elif from_direction == "right":
            return (coord, 0)
        return (height // 2, width // 2)

    def get_game_state(self):
        """
        Zwraca dict z aktualnym stanem gry (mapy + gracze).
        """
        with self.lock:
            state = {
                "current_room": self.current_room,
                "players": {},
                "maps": {}
            }
            for rname, rmap in self.maps.items():
                state["maps"][rname] = ["".join(row) for row in rmap]

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
    Dodano obsługę "restart_game" -> tworzy nowy obiekt SnakeGame.
    """

    def __init__(self):
        self.game = SnakeGame()  # Główna logika gry
        self.running = True

        # Połączenie i kanał do konsumowania
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
            self.consume_channel.basic_consume(
                queue=self.server_queue,
                on_message_callback=self.on_request,
                auto_ack=True
            )
            print("[SERVER] Połączenie do konsumowania utworzone.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] Nie udało się połączyć z RabbitMQ do konsumowania: {e}")
            self.running = False

        # Połączenie i kanał do publikowania
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
            self.publish_channel.exchange_declare(exchange=self.game_state_exchange, exchange_type='fanout')
            print("[SERVER] Połączenie do publikowania utworzone.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] Nie udało się połączyć z RabbitMQ do publikowania: {e}")
            self.running = False

        # Uruchamiamy wątek update
        if self.running:
            self.update_thread = threading.Thread(target=self.game_loop, daemon=True)
            self.update_thread.start()
            print("[SERVER] Wątek game_loop uruchomiony.")

    def on_request(self, ch, method, props, body):
        """
        Callback obsługujący wiadomości od klientów.
        Obsługuje:
          - join_game (dołączenie do gry)
          - player_move (ruch gracza)
          - restart_game (reset stanu gry)
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
                    print(f"[SERVER] Gracz {player_id} NIE dołączył.")
        elif msg_type == "player_move":
            player_id = str(message.get("player_id"))
            direction = message.get("direction")
            if player_id and direction:
                self.game.update_player_direction(player_id, direction)
                print(f"[SERVER] Gracz {player_id} -> '{direction}'")
        elif msg_type == "restart_game":
            # Dowolny gracz może zrestartować
            print("[SERVER] Otrzymano żądanie restartu gry!")
            self.game = SnakeGame()  # tworzony nowy obiekt logiki
            print("[SERVER] Gra zrestartowana.")
        else:
            print(f"[WARN] Nieznany typ wiadomości: {msg_type}")

    def game_loop(self):
        """
        Wątek aktualizacji gry i publikowania stanu.
        """
        while self.running:
            self.game.update()
            state = self.game.get_game_state()
            # publikacja stanu
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
        if not self.running:
            print("[SERVER] Serwer nie wystartował poprawnie.")
            return
        print("[SERVER] Serwer wystartował. Oczekiwanie na klientów...")
        try:
            self.consume_channel.start_consuming()
        except KeyboardInterrupt:
            print("[SERVER] Przerwano serwer (Ctrl+C).")
        finally:
            self.running = False
            # sprzątanie
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
