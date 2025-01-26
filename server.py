#!/usr/bin/env python3

import os
import threading
import time
import json
import random
import pika

UPDATE_INTERVAL = 0.2
MAX_PLAYERS = 6

MAP_ORDER = ["room0", "room1", "room2", "room3"]  # 4 mapy
APPLE_GOAL = 5  # ile jabłek trzeba na każdej mapie
APPLES_MINIMUM = 5  # ile minimalnie jabłek ma być na mapie

WALL = '#'
APPLE = 'O'
EMPTY = '.'

# Kierunki vim
DIRECTIONS = {
    'h': (0, -1),
    'l': (0, 1),
    'k': (-1, 0),
    'j': (1, 0)
}


class SnakeGame:
    """
    Logika jednej mapy (jednej rundy).
    Każdy gracz -> {positions, direction, alive, room, lastDir, apples}.
    apples = ile jabłek zebrano w TEJ mapie.
    """
    def __init__(self, maps_folder="maps", start_map="room0"):
        self.maps = {}
        self.load_maps(maps_folder)
        if start_map not in self.maps and self.maps:
            start_map = list(self.maps.keys())[0]
        self.current_map = start_map

        self.height = len(self.maps[self.current_map])
        self.width = len(self.maps[self.current_map][0])
        self.players = {}  # {pid: {...}}
        self.player_count = 0
        self.lock = threading.Lock()
        self.start_positions = self.generate_start_positions()

    def load_maps(self, folder):
        if not os.path.isdir(folder):
            print(f"[ERROR] Katalog '{folder}' nie istnieje.")
            return
        for fn in os.listdir(folder):
            if fn.endswith(".txt"):
                mname = fn.replace(".txt","")
                with open(os.path.join(folder, fn),'r') as f:
                    lines = [list(line.rstrip('\n')) for line in f]
                self.maps[mname] = lines
                print(f"[INFO] Wczytano mapę '{mname}'.")

    def generate_start_positions(self):
        center_row = self.height//2
        center_col = self.width//2
        offsets = [-2,-1,0,1,2,3]
        positions=[]
        for off in offsets:
            y = center_row
            x = center_col+off
            positions.append((self.current_map,y,x))
        return positions

    def add_player(self, pid):
        with self.lock:
            if self.player_count>=MAX_PLAYERS:
                return False

            if self.player_count < len(self.start_positions):
                (m,sy,sx)=self.start_positions[self.player_count]
            else:
                m = self.current_map
                sy=self.height//2
                sx=self.width//2

            if not self.is_empty_cell(m, sy,sx):
                found=False
                for y in range(1,self.height-1):
                    for x in range(1,self.width-1):
                        if self.is_empty_cell(m,y,x):
                            sy,sx=y,x
                            found=True
                            break
                    if found:
                        break
                if not found:
                    print(f"[ERROR] Brak miejsca dla gracza {pid}.")
                    return False

            self.players[pid] = {
                "positions": [(sy,sx)],
                "direction": (0,0),
                "alive": True,
                "room": m,
                "lastDir": None,
                "apples": 0
            }
            self.player_count+=1
            print(f"[INFO] Dodano gracza {pid} -> map={m}, pos=({sy},{sx})")
            return True

    def remove_player(self, pid):
        with self.lock:
            if pid in self.players:
                del self.players[pid]
                self.player_count-=1

    def is_empty_cell(self, m, y, x):
        cell = self.maps[m][y][x]
        return (cell!=WALL)

    def update_player_direction(self, pid, d):
        with self.lock:
            p = self.players.get(pid)
            if p and p["alive"]:
                if d in DIRECTIONS:
                    p["direction"] = DIRECTIONS[d]
                    p["lastDir"] = d

    def update(self):
        # standard
        with self.lock:
            dead=[]
            for pid, p in self.players.items():
                if not p["alive"]:
                    continue
                (dy,dx) = p["direction"]
                if (dy,dx)==(0,0):
                    continue
                head_y, head_x = p["positions"][0]
                ny = head_y+dy
                nx = head_x+dx
                rm = p["room"]

                if ny<0 or ny>=self.height or nx<0 or nx>=self.width:
                    p["alive"]=False
                    dead.append(pid)
                    continue
                if self.maps[rm][ny][nx] == WALL:
                    p["alive"]=False
                    dead.append(pid)
                    continue

                # kolizja węży
                for opid,opdata in self.players.items():
                    if not opdata["alive"]:
                        continue
                    if opid==pid:
                        if (ny,nx) in opdata["positions"]:
                            p["alive"]=False
                            dead.append(pid)
                            break
                    else:
                        if opdata["room"]==rm and (ny,nx) in opdata["positions"]:
                            p["alive"]=False
                            dead.append(pid)
                            break
                if pid in dead:
                    continue

                # ruch
                p["positions"].insert(0,(ny,nx))
                if self.maps[rm][ny][nx]==APPLE:
                    # rośniemy
                    self.maps[rm][ny][nx]=EMPTY
                    p["apples"]+=1
                else:
                    p["positions"].pop()

    def get_game_state(self):
        st = {
            "current_room": self.current_map,
            "players": {},
            "maps": {}
        }
        for rname,rmap in self.maps.items():
            st["maps"][rname] = ["".join(row) for row in rmap]
        for pid,pdata in self.players.items():
            st["players"][pid] = {
                "positions": pdata["positions"],
                "alive": pdata["alive"],
                "room": pdata["room"],
                "lastDir": pdata["lastDir"],
                "apples": pdata["apples"]
            }
        return st


class SnakeServer:
    """
    Serwer z 2 polaczeniami do RabbitMQ (consume + publish).
    4 mapy => mapIndex=0..3
    Kazda wymaga APPLE_GOAL (5) jabłek.
    Gdy player ma apples>=5 => next map => reset węży (ale gracze ci sami).
    Gdy mapIndex>3 => gameOver.
    'r' => restart do mapIndex=0, nowy SnakeGame, wszyscy gracze dodani od nowa.
    """
    def __init__(self):
        self.mapIndex = 0
        self.connected_players = set()
        self.gameOver = False
        self.winner = None
        self.game = SnakeGame(start_map=MAP_ORDER[self.mapIndex])

        # polaczenie do CONSUME
        try:
            self.consume_conn = pika.BlockingConnection(
                pika.ConnectionParameters(host='localhost')
            )
            self.consume_ch = self.consume_conn.channel()
            self.server_queue = "server_queue"
            self.consume_ch.queue_declare(queue=self.server_queue)
            self.consume_ch.basic_consume(
                queue=self.server_queue,
                on_message_callback=self.on_request,
                auto_ack=True
            )
            print("[SERVER] Polaczenie do consume OK.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] consume connect fail: {e}")
            return

        # polaczenie do PUBLISH
        try:
            self.publish_conn = pika.BlockingConnection(
                pika.ConnectionParameters(host='localhost')
            )
            self.publish_ch = self.publish_conn.channel()
            self.game_state_exchange = "game_state_exchange"
            self.publish_ch.exchange_declare(exchange=self.game_state_exchange, exchange_type='fanout')
            print("[SERVER] Polaczenie do publish OK.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] publish connect fail: {e}")
            return

        self.running = True
        self.update_thread = threading.Thread(target=self.game_loop, daemon=True)
        self.update_thread.start()
        print("[SERVER] Watek game_loop uruchomiony.")

    def on_request(self, ch, method, props, body):
        try:
            msg = json.loads(body.decode("utf-8"))
        except:
            print("[WARN] Niepoprawny JSON.")
            return
        mtype = msg.get("type","")
        pid = str(msg.get("player_id",""))

        if mtype=="join_game":
            if pid:
                self.connected_players.add(pid)
                self.game.add_player(pid)
        elif mtype=="player_move":
            direction = msg.get("direction","")
            if pid and direction:
                self.game.update_player_direction(pid, direction)
        elif mtype=="restart_game":
            # globalny restart => mapIndex=0, new SnakeGame, dodaj gracze
            print("[SERVER] Global restart -> do map0.")
            self.mapIndex=0
            self.gameOver=False
            self.winner=None
            self.game = SnakeGame(start_map=MAP_ORDER[self.mapIndex])
            for p in self.connected_players:
                self.game.add_player(p)
        else:
            print(f"[WARN] Nieznany typ={mtype}")

    def spawn_min_apples(self):
        """
        W danej mapie -> co najmniej APPLES_MINIMUM jabłek
        """
        minApples = APPLES_MINIMUM
        rm = self.game.current_map
        room_map = self.game.maps[rm]
        apples_count=0
        for row in room_map:
            apples_count += row.count(APPLE)
        while apples_count<minApples:
            free=[]
            for y in range(1, self.game.height-1):
                for x in range(1, self.game.width-1):
                    if room_map[y][x] in ('.',EMPTY):
                        # check snake
                        if not self.is_snake_on_cell(y,x):
                            free.append((y,x))
            if not free:
                print("[WARN] brak miejsca na jabłka")
                break
            (ry,rx)=random.choice(free)
            room_map[ry][rx] = APPLE
            apples_count+=1

    def is_snake_on_cell(self, y, x):
        for pid,pdata in self.game.players.items():
            if pdata["alive"] and (y,x) in pdata["positions"]:
                return True
        return False

    def check_if_map_completed(self):
        """
        Jeśli którykolwiek gracz ma apples>=5 => next map
        """
        for pid, pdata in self.game.players.items():
            if pdata["apples"]>=APPLE_GOAL:
                # gracze przechodza do next map
                self.mapIndex+=1
                if self.mapIndex>=len(MAP_ORDER):
                    # koniec
                    self.gameOver=True
                    self.winner = pid
                    self.running=False
                    print(f"[SERVER] KONIEC GRY => winner={pid}")
                else:
                    print(f"[SERVER] Gracz {pid} zdobyl {APPLE_GOAL} jablek => next map {self.mapIndex}")
                    newmap = MAP_ORDER[self.mapIndex]
                    self.game = SnakeGame(start_map=newmap)
                    # dodajmy ponownie wszystkich
                    for p in self.connected_players:
                        self.game.add_player(p)
                break

    def game_loop(self):
        while self.running:
            if self.gameOver:
                break

            self.spawn_min_apples()
            self.game.update()
            self.check_if_map_completed()

            state = self.game.get_game_state()
            state["gameOver"] = self.gameOver
            state["winner"] = self.winner

            # publikuj
            try:
                self.publish_ch.basic_publish(
                    exchange=self.game_state_exchange,
                    routing_key='',
                    body=json.dumps(state)
                )
            except pika.exceptions.AMQPError as e:
                print(f"[ERROR] Publish: {e}")
                self.running=False

            time.sleep(UPDATE_INTERVAL)

    def start_server(self):
        if not self.running:
            print("[SERVER] Nie wystartował poprawnie.")
            return
        print("[SERVER] Serwer wystartował. Oczekiwanie na klientów...")
        try:
            self.consume_ch.start_consuming()
        except KeyboardInterrupt:
            print("[SERVER] Przerwano (Ctrl+C).")
        finally:
            self.running=False
            try:
                self.consume_ch.stop_consuming()
            except:
                pass
            if self.update_thread.is_alive():
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


if __name__=="__main__":
    srv = SnakeServer()
    srv.start_server()
