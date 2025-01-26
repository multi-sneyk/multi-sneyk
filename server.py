#!/usr/bin/env python3

"""
Serwer Snake:
- 4 mapy: room0..room3
- Każda mapa wymaga 5 punktów (czyli 5 jabłek) do przejścia na kolejną.
- Punkty resetują się przy przejściu na nową mapę.
- globalny klawisz 'r' -> restart do mapy0, zeruje wszystko.
- ranking graczy opiera się na "apples" w aktualnej mapie (liczba jabłek).
- Po ukończeniu mapy3 (czwartej), jeśli ktoś zbierze 5 jabłek, gra się kończy:
  zwycięzca -> "Gratulacje, jestes mistrzem sterowania VIMem"
  reszta -> "Leszcz".
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
POINTS_PER_MAP = 5  # na każdej mapie trzeba 5 jabłek
APPLES_ON_MAP = [5, 5, 5, 5]  # minimalna liczba jabłek (możesz zwiększyć)

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
    """
    Logika jednej mapy (jednej rundy).
    Każdy gracz ma:
      positions, direction, alive, room, lastDir (kierunek do rysowania głowy),
      apples (ile jabłek w tej mapie).
    """
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

        self.players = {}  # pid -> {...}
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
        offsets = [-2,-1,0,1,2,3]
        positions=[]
        for off in offsets:
            y = center_row
            x = center_col + off
            positions.append((self.current_room,y,x))
        return positions

    def add_player(self, pid):
        if self.player_count>=MAX_PLAYERS:
            return False
        if self.player_count < len(self.start_positions):
            (rm, sy, sx) = self.start_positions[self.player_count]
        else:
            rm = self.current_room
            sy = self.height//2
            sx = self.width//2

        if not self.is_empty_cell(rm, sy, sx):
            found=False
            for y in range(1, self.height-1):
                for x in range(1, self.width-1):
                    if self.is_empty_cell(rm, y,x):
                        sy,sx=y,x
                        found=True
                        break
                if found:
                    break
            if not found:
                print(f"[ERROR] Brak miejsca dla gracza {pid}.")
                return False

        # gracz ma 0 jabłek na tej mapie
        self.players[pid] = {
            "positions": [(sy,sx)],
            "direction": (0,0),
            "alive": True,
            "room": rm,
            "lastDir": None,  # do rysowania głowy
            "apples": 0       # ile jabłek w tej mapie
        }
        self.player_count+=1
        print(f"[INFO] Dodano gracza {pid} w mapie={rm}, pos=({sy},{sx})")
        return True

    def remove_player(self, pid):
        if pid in self.players:
            del self.players[pid]
            self.player_count -=1

    def is_empty_cell(self, rm, y, x):
        cell = self.maps[rm][y][x]
        return (cell != WALL)

    def update_player_direction(self, pid, direction):
        p = self.players.get(pid)
        if p and p["alive"]:
            if direction in DIRECTIONS:
                p["direction"] = DIRECTIONS[direction]
                p["lastDir"] = direction

    def update(self):
        """
        Aktualizujemy węże:
        - rosną po napotkaniu 'O' (usuwamy 'O' z mapy).
        - w polu gracza jest "apples" => zliczamy w serwerze?
          Tutaj do zliczania wystarczyłoby p["apples"]++. (robimy to TUTAJ, by uprościć)
        """
        with self.lock:
            dead_pids=[]
            for pid, p in self.players.items():
                if not p["alive"]:
                    continue
                (dy, dx) = p["direction"]
                if (dy,dx)==(0,0):
                    continue
                head_y, head_x = p["positions"][0]
                ny = head_y + dy
                nx = head_x + dx
                rm = p["room"]

                # wyjście poza mapę?
                if ny<0 or ny>=self.height or nx<0 or nx>=self.width:
                    p["alive"]=False
                    dead_pids.append(pid)
                    continue
                if self.maps[rm][ny][nx] == WALL:
                    p["alive"]=False
                    dead_pids.append(pid)
                    continue

                # kolizja z wężem
                for opid, opdata in self.players.items():
                    if not opdata["alive"]:
                        continue
                    if opid==pid:
                        if (ny,nx) in opdata["positions"]:
                            p["alive"]=False
                            dead_pids.append(pid)
                            break
                    else:
                        if opdata["room"]==rm and (ny,nx) in opdata["positions"]:
                            p["alive"]=False
                            dead_pids.append(pid)
                            break
                if pid in dead_pids:
                    continue

                # normalny ruch
                p["positions"].insert(0, (ny,nx))
                if self.maps[rm][ny][nx] == APPLE:
                    # rośniemy
                    self.maps[rm][ny][nx] = EMPTY
                    # plus jabłko do p["apples"]
                    p["apples"] +=1
                else:
                    # normalny ruch => usuń ogon
                    p["positions"].pop()

    def get_game_state(self):
        """
        Zwraca stan mapy i węży, łącznie z liczbą jabłek p["apples"] w aktualnej mapie
        (przyda się do rankingu).
        """
        st = {
            "current_room": self.current_room,
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
    Serwer:
    - mapIndex 0..3 -> 4 mapy
    - Każda mapa wymaga 5 jabłek (apples=5) do przejścia
    - 'r' => globalny restart do mapIndex=0 i usunięcie wszystkich węży => nowy SnakeGame
    - Ranking wg liczby p["apples"] (malejąco).
    - Gdy ktoś na mapie=3 uzbiera 5 jabłek => koniec gry (ktoś wygrał).
      - Zwycięzca => "Gratulacje..."
      - Reszta => "Leszcz"
    """
    def __init__(self):
        self.mapIndex = 0
        self.connected_players = set()

        self.gameOver = False
        self.winner = None

        # startowa gra
        startMap = MAP_ORDER[self.mapIndex]
        self.game = SnakeGame(start_room=startMap)
        self.running=True

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
            self.running=False

        try:
            self.publish_conn = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host='localhost', port=5672, virtual_host='/',
                    credentials=pika.PlainCredentials('adminowiec','.p=o!v0cD5kK2+F3,{c1&DB')
                )
            )
            self.publish_ch = self.publish_conn.channel()
            self.game_state_exchange = "game_state_exchange"
            self.publish_ch.exchange_declare(
                exchange=self.game_state_exchange,
                exchange_type='fanout'
            )
            print("[SERVER] Połączenie publish OK.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] publish connect fail: {e}")
            self.running=False

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

        if mtype=="join_game":
            if pid:
                self.connected_players.add(pid)
                # dodaj do aktualnej mapy
                self.game.add_player(pid)

        elif mtype=="player_move":
            direction = msg.get("direction","")
            if pid and direction:
                self.game.update_player_direction(pid, direction)

        elif mtype=="restart_game":
            # globalny restart -> mapIndex=0, nowy SnakeGame("room0"), usuwamy graczy i dodajemy od nowa
            print("[SERVER] Globalny restart do mapy0.")
            self.mapIndex=0
            newMap = MAP_ORDER[self.mapIndex]
            self.game = SnakeGame(start_room=newMap)
            for p in self.connected_players:
                self.game.add_player(p)
            self.gameOver=False
            self.winner=None

        else:
            print(f"[WARN] Nieznany mtype={mtype}")

    def spawn_minimum_apples(self):
        """
        Utrzymuje minimalną liczbę jabłek = APPLES_ON_MAP[self.mapIndex].
        """
        need = APPLES_ON_MAP[self.mapIndex]
        rm = self.game.current_room
        room_map = self.game.maps[rm]
        apples_count=0
        for row in room_map:
            apples_count += row.count(APPLE)

        while apples_count<need:
            free=[]
            for y in range(1, self.game.height-1):
                for x in range(1, self.game.width-1):
                    if room_map[y][x] in ('.', EMPTY):
                        # sprawdź, czy wąż
                        if not self.is_snake_on_cell(y,x):
                            free.append((y,x))
            if not free:
                print("[WARN] Brak miejsca na jabłka.")
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
        Sprawdza, czy któryś gracz zebrał 5 jabłek (w self.game).
        Jeśli tak -> next map (mapIndex++)
        Jeśli mapIndex>3 -> end_game
        Uwaga: może być kilka graczy z 5 jabłek w tym samym ticku, weźmy pierwszego?
        Można losowo, albo brać 'pierwszego w pętli'.
        """
        for pid,pdata in self.game.players.items():
            if pdata["apples"]>=POINTS_PER_MAP:  # 5
                # przesuwamy na nast. mapę
                winner_pid = pid
                print(f"[SERVER] Gracz {pid} ukończył mapę {self.mapIndex} (5 jabłek).")
                self.mapIndex+=1
                if self.mapIndex>=len(MAP_ORDER):
                    # koniec
                    self.end_game(winner_pid)
                else:
                    # reset do nowej mapy: new SnakeGame(MAP_ORDER[self.mapIndex])
                    nextMap = MAP_ORDER[self.mapIndex]
                    print(f"[SERVER] Przechodzimy do mapy {self.mapIndex} => {nextMap}")
                    self.game = SnakeGame(start_room=nextMap)
                    # dodaj graczy od nowa (zerując ich 'apples')
                    for cpid in self.connected_players:
                        self.game.add_player(cpid)
                # wystarczy przerwać pętlę
                break

    def end_game(self, winner_pid):
        self.gameOver=True
        self.winner=winner_pid
        self.running=False
        print(f"[SERVER] KONIEC GRY => zwycięzca {winner_pid}")

    def game_loop(self):
        while self.running:
            if self.gameOver:
                break

            self.spawn_minimum_apples()

            self.game.update()
            # sprawdzamy, czy ktoś zebrał 5 jabłek => next map
            self.check_if_map_completed()

            # publikacja
            st = self.game.get_game_state()
            st["gameOver"] = self.gameOver
            st["winner"] = self.winner
            # Ranking => posortuj graczy wg apples malejąco
            # (nie jest to osobne pole w JSON, ale klienci mogą sami sortować, ewent. zrobimy "ranking"
            # Klient ma info st["players"][pid]["apples"]

            try:
                self.publish_conn.channel().basic_publish(
                    exchange="game_state_exchange",
                    routing_key='',
                    body=json.dumps(st)
                )
            except pika.exceptions.AMQPError as e:
                print(f"[ERROR] publish: {e}")
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
            print("[SERVER] Przerwano serwer (Ctrl+C).")
        finally:
            self.running=False
            try:
                self.consume_ch.stop_consuming()
            except:
                pass
            if hasattr(self,'update_thread') and self.update_thread.is_alive():
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
