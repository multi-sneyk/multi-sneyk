#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Serwer Snake (wielu graczy).
- 4 mapy: room0..room3
- Każda mapa wymaga 5 punktów (5 jabłek) do przejścia na następną.
- Punkty resetują się przy przejściu na nową mapę.
- 'r' (po stronie klienta) -> globalny restart do mapy0.
- Po zebraniu 5 jabłek na mapie3 -> koniec gry, komunikat o wygranym.

Obsługuje jednocześnie wielu klientów (player_id).
"""

import os
import threading
import time
import json
import random
import pika

UPDATE_INTERVAL = 0.2
MAX_PLAYERS = 6

MAP_ORDER = ["room0", "room1", "room2", "room3"]  # 4 mapy
POINTS_PER_MAP = 5   # na każdej mapie trzeba 5 jabłek
APPLES_ON_MAP = [5, 5, 5, 5]  # minimalna liczba jabłek na każdej mapie

WALL = '#'
APPLE = 'O'
EMPTY = '.'

DIRECTIONS = {
    'h': (0, -1),
    'l': (0, 1),
    'k': (-1, 0),
    'j': (1, 0)
}

class SnakeGame:
    def __init__(self, maps_folder="maps", start_room="room0"):
        self.maps = {}
        self.load_maps(maps_folder)

        if start_room not in self.maps:
            if self.maps:
                start_room = list(self.maps.keys())[0]
            else:
                raise ValueError("Brak map w folderze.")

        self.current_room = start_room
        self.height = len(self.maps[start_room])
        self.width = len(self.maps[start_room][0])

        self.players = {}   # pid -> ...
        self.player_count = 0
        self.lock = threading.Lock()

        self.start_positions = self.generate_start_positions()

    def load_maps(self, folder):
        if not os.path.isdir(folder):
            print(f"[ERROR] Katalog '{folder}' nie istnieje.")
            return
        for filename in os.listdir(folder):
            if filename.endswith(".txt"):
                rname = filename.replace(".txt","")
                path = os.path.join(folder, filename)
                with open(path,'r') as f:
                    lines = [list(line.rstrip('\n')) for line in f]
                self.maps[rname] = lines
                print(f"[INFO] Wczytano mapę '{rname}'.")

    def generate_start_positions(self):
        center_row = self.height // 2
        center_col = self.width // 2
        offsets = [-2, -1, 0, 1, 2, 3]
        positions = []
        for off in offsets:
            y = center_row
            x = center_col + off
            positions.append((self.current_room, y, x))
        return positions

    def add_player(self, pid):
        with self.lock:
            if self.player_count >= MAX_PLAYERS:
                print(f"[WARN] Limit graczy ({MAX_PLAYERS}) osiągnięty. Nie dodano {pid}.")
                return False

            if self.player_count < len(self.start_positions):
                (rm, sy, sx) = self.start_positions[self.player_count]
            else:
                rm = self.current_room
                sy = self.height // 2
                sx = self.width // 2

            if not self.is_empty_cell(rm, sy, sx):
                found = False
                for y in range(1, self.height - 1):
                    for x in range(1, self.width - 1):
                        if self.is_empty_cell(rm, y, x):
                            sy, sx = y, x
                            found = True
                            break
                    if found:
                        break
                if not found:
                    print(f"[ERROR] Brak miejsca dla gracza {pid}.")
                    return False

            self.players[pid] = {
                "positions": [(sy, sx)],
                "direction": (0, 0),
                "alive": True,
                "room": rm,
                "lastDir": None,
                "apples": 0
            }
            self.player_count += 1
            print(f"[INFO] Dodano gracza {pid} w mapie={rm}, pos=({sy},{sx})")
            return True

    def remove_player(self, pid):
        with self.lock:
            if pid in self.players:
                del self.players[pid]
                self.player_count -= 1

    def is_empty_cell(self, rm, y, x):
        cell = self.maps[rm][y][x]
        return (cell != WALL)

    def update_player_direction(self, pid, direction):
        with self.lock:
            p = self.players.get(pid)
            if p and p["alive"]:
                if direction in DIRECTIONS:
                    p["direction"] = DIRECTIONS[direction]
                    p["lastDir"] = direction

    def update(self):
        """
        Ruch węży, rośnięcie po zjedzeniu jabłka, sprawdzanie kolizji.
        """
        with self.lock:
            dead_pids = []
            for pid, p in self.players.items():
                if not p["alive"]:
                    continue
                dy, dx = p["direction"]
                if (dy, dx) == (0, 0):
                    continue
                head_y, head_x = p["positions"][0]
                ny = head_y + dy
                nx = head_x + dx
                rm = p["room"]

                # Wyjście poza mapę
                if ny < 0 or ny >= self.height or nx < 0 or nx >= self.width:
                    p["alive"] = False
                    dead_pids.append(pid)
                    continue
                if self.maps[rm][ny][nx] == WALL:
                    p["alive"] = False
                    dead_pids.append(pid)
                    continue

                # kolizje z wężami
                for opid, opdata in self.players.items():
                    if not opdata["alive"]:
                        continue
                    if opid == pid:
                        if (ny, nx) in opdata["positions"]:
                            p["alive"] = False
                            dead_pids.append(pid)
                            break
                    else:
                        if opdata["room"] == rm and (ny, nx) in opdata["positions"]:
                            p["alive"] = False
                            dead_pids.append(pid)
                            break
                if pid in dead_pids:
                    continue

                # normalny ruch
                p["positions"].insert(0, (ny, nx))
                if self.maps[rm][ny][nx] == APPLE:
                    self.maps[rm][ny][nx] = EMPTY
                    p["apples"] += 1
                else:
                    p["positions"].pop()

    def get_game_state(self):
        """
        Zwraca dict z info o mapie, wężach itd.
        """
        st = {
            "current_room": self.current_room,
            "players": {},
            "maps": {}
        }
        for rname, rmap in self.maps.items():
            st["maps"][rname] = ["".join(row) for row in rmap]

        for pid, pdata in self.players.items():
            st["players"][pid] = {
                "positions": pdata["positions"],
                "alive": pdata["alive"],
                "room": pdata["room"],
                "lastDir": pdata["lastDir"],
                "apples": pdata["apples"]
            }
        return st

class SnakeServer:
    def __init__(self):
        self.mapIndex = 0
        self.connected_players = set()

        self.gameOver = False
        self.winner = None

        startMap = MAP_ORDER[self.mapIndex]
        self.game = SnakeGame(start_room=startMap)
        self.running = True

        try:
            self.consume_conn = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host='localhost', port=5672, virtual_host='/',
                    credentials=pika.PlainCredentials('adminowiec','.p=o!v0cD5kK2+F3,{c1&DB')
                )
            )
            self.consume_ch = self.consume_conn.channel()
            self.server_queue = "server_queue"
            self.consume_ch.queue_declare(queue=self.server_queue)
            self.consume_ch.basic_consume(
                queue=self.server_queue,
                on_message_callback=self.on_request,
                auto_ack=True
            )
            print("[SERVER] Połączenie consume OK.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] consume connect fail: {e}")
            self.running = False

        try:
            self.publish_conn = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host='localhost', port=5672, virtual_host='/',
                    credentials=pika.PlainCredentials('adminowiec','.p=o!v0cD5kK2+F3,{c1&DB')
                )
            )
            self.publish_ch = self.publish_conn.channel()
            self.game_state_exchange = "game_state_exchange"
            self.publish_ch.exchange_declare(exchange=self.game_state_exchange, exchange_type='fanout')
            print("[SERVER] Połączenie publish OK.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] publish connect fail: {e}")
            self.running = False

        if self.running:
            self.update_thread = threading.Thread(target=self.game_loop, daemon=True)
            self.update_thread.start()
            print("[SERVER] Wątek game_loop uruchomiony.")

    def on_request(self, ch, method, props, body):
        try:
            msg = json.loads(body.decode("utf-8"))
        except:
            print("[WARN] Niepoprawny JSON.")
            return
        mtype = msg.get("type","")
        pid = str(msg.get("player_id",""))

        if mtype == "join_game":
            if pid:
                self.connected_players.add(pid)
                ok = self.game.add_player(pid)
                print(f"[SERVER] join_game -> Gracz {pid}, status={ok}")
        elif mtype == "player_move":
            direction = msg.get("direction","")
            if pid and direction:
                self.game.update_player_direction(pid, direction)
        elif mtype == "restart_game":
            print("[SERVER] Globalny restart -> mapIndex=0")
            self.mapIndex = 0
            newMap = MAP_ORDER[self.mapIndex]
            self.game = SnakeGame(start_room=newMap)
            for p in self.connected_players:
                self.game.add_player(p)
            self.gameOver = False
            self.winner = None
        else:
            print(f"[WARN] Nieznany mtype={mtype}")

    def spawn_minimum_apples(self):
        need = APPLES_ON_MAP[self.mapIndex]
        rm = self.game.current_room
        room_map = self.game.maps[rm]
        apples_count = 0
        for row in room_map:
            apples_count += row.count(APPLE)

        while apples_count < need:
            free = []
            for y in range(1, self.game.height - 1):
                for x in range(1, self.game.width - 1):
                    if room_map[y][x] in ('.', EMPTY):
                        if not self.is_snake_on_cell(y, x):
                            free.append((y, x))
            if not free:
                print("[WARN] Brak miejsca na jabłka.")
                break
            ry, rx = random.choice(free)
            room_map[ry][rx] = APPLE
            apples_count += 1

    def is_snake_on_cell(self, y, x):
        for pid, pdata in self.game.players.items():
            if pdata["alive"] and (y, x) in pdata["positions"]:
                return True
        return False

    def check_if_map_completed(self):
        for pid, pdata in self.game.players.items():
            if pdata["apples"] >= POINTS_PER_MAP:
                print(f"[SERVER] Gracz {pid} ukończył mapę {self.mapIndex}")
                self.mapIndex += 1
                if self.mapIndex >= len(MAP_ORDER):
                    self.end_game(pid)
                else:
                    nextMap = MAP_ORDER[self.mapIndex]
                    print(f"[SERVER] Nowa mapa: {nextMap}")
                    self.game = SnakeGame(start_room=nextMap)
                    for cpid in self.connected_players:
                        self.game.add_player(cpid)
                break

    def end_game(self, winner_pid):
        self.gameOver = True
        self.winner = winner_pid
        self.running = False
        print(f"[SERVER] KONIEC GRY => zwycięzca {winner_pid}")

    def game_loop(self):
        while self.running:
            if self.gameOver:
                break

            self.spawn_minimum_apples()
            self.game.update()
            self.check_if_map_completed()

            st = self.game.get_game_state()
            st["gameOver"] = self.gameOver
            st["winner"] = self.winner

            try:
                self.publish_ch.basic_publish(
                    exchange=self.game_state_exchange,
                    routing_key='',
                    body=json.dumps(st)
                )
            except pika.exceptions.AMQPError as e:
                print(f"[ERROR] publish: {e}")
                self.running = False

            time.sleep(UPDATE_INTERVAL)

    def start_server(self):
        if not self.running:
            print("[SERVER] Serwer nie wystartował prawidłowo.")
            return
        print("[SERVER] Serwer wystartował. Oczekiwanie na klientów...")
        try:
            self.consume_ch.start_consuming()
        except KeyboardInterrupt:
            print("[SERVER] Przerwano serwer (Ctrl+C).")
        finally:
            self.running = False
            try:
                self.consume_ch.stop_consuming()
            except:
                pass
            if hasattr(self, 'update_thread') and self.update_thread.is_alive():
                self.update_thread.join()

            try:
                self.consume_conn.close()
            except:
                pass
            try:
                self.publish_conn.close()
            except:
                pass
            print("[SERVER] Serwer zamknięty.")


if __name__ == "__main__":
    srv = SnakeServer()
    srv.start_server()
