#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import threading
import time
import curses
import pika

# Zamiana klawiszy -> kierunki
KEY_TO_DIRECTION = {
    ord('h'): 'h',
    ord('j'): 'j',
    ord('k'): 'k',
    ord('l'): 'l'
}

# Kierunek -> znak głowy
DIR_TO_HEAD = {
    'k': '^',
    'j': 'v',
    'h': '<',
    'l': '>'
}

class SnakeClient:
    def __init__(self, player_id, host="localhost", user="adminowiec", password=".p=o!v0cD5kK2+F3,{c1&DB"):
        self.player_id = str(player_id)
        self.host = host
        self.user = user
        self.password = password

        self.running = True
        self.game_state = {}

        # Tryby ekranu: "start", "description", "game", "exit"
        self.screen_mode = "start"

        # Zmienna, by wiedzieć, czy już połączyliśmy się z RabbitMQ
        self.rabbit_connected = False

    # ---------------------
    # Funkcje RabbitMQ
    # ---------------------

    def connect_rabbit(self):
        """Łączy się z RabbitMQ (2 połączenia: publish + consume)."""
        if self.rabbit_connected:
            return

        try:
            self.publish_conn = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=self.host, port=5672, virtual_host='/',
                    credentials=pika.PlainCredentials(self.user, self.password)
                )
            )
            self.publish_ch = self.publish_conn.channel()
            self.server_queue = "server_queue"
            print("[CLIENT] Publish connect OK.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] Publish connect fail: {e}")
            self.running = False
            return

        try:
            self.consume_conn = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=self.host, port=5672, virtual_host='/',
                    credentials=pika.PlainCredentials(self.user, self.password)
                )
            )
            self.consume_ch = self.consume_conn.channel()
            self.game_state_exchange = "game_state_exchange"
            self.consume_ch.exchange_declare(exchange=self.game_state_exchange, exchange_type='fanout')

            res = self.consume_ch.queue_declare(queue='', exclusive=True)
            self.client_queue = res.method.queue
            self.consume_ch.queue_bind(exchange=self.game_state_exchange, queue=self.client_queue)
            print("[CLIENT] Consume connect OK.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] Consume connect fail: {e}")
            self.running = False
            return

        # Wątek nasłuchu
        self.listen_thread = threading.Thread(target=self.listen_loop, daemon=True)
        self.listen_thread.start()

        self.rabbit_connected = True

    def listen_loop(self):
        def callback(ch, method, props, body):
            try:
                st = json.loads(body.decode("utf-8"))
                self.game_state = st
            except:
                pass

        self.consume_ch.basic_consume(
            queue=self.client_queue,
            on_message_callback=callback,
            auto_ack=True
        )
        try:
            self.consume_ch.start_consuming()
        except:
            pass
        self.running=False

    def send_to_server(self, data):
        if not self.rabbit_connected:
            return
        try:
            self.publish_ch.basic_publish(
                exchange='',
                routing_key=self.server_queue,
                body=json.dumps(data)
            )
        except:
            pass

    def join_game(self):
        msg = {
            "type":"join_game",
            "player_id": self.player_id
        }
        self.send_to_server(msg)
        print(f"[CLIENT] Wysłano join_game (pid={self.player_id}).")

    def send_move(self, direction):
        msg = {
            "type":"player_move",
            "player_id": self.player_id,
            "direction": direction
        }
        self.send_to_server(msg)

    def send_restart(self):
        msg = {
            "type":"restart_game",
            "player_id": self.player_id
        }
        self.send_to_server(msg)
        print("[CLIENT] Globalny restart => map0")

    # ---------------------
    # Pętla curses
    # ---------------------

    def run_curses(self):
        curses.wrapper(self.main_curses_loop)

    def main_curses_loop(self, stdscr):
        curses.curs_set(0)
        stdscr.nodelay(True)

        while self.running:
            try:
                key = stdscr.getch()
                if self.screen_mode == "start":
                    self.handle_start_screen(stdscr, key)
                elif self.screen_mode == "description":
                    self.handle_description_screen(stdscr, key)
                elif self.screen_mode == "game":
                    self.handle_game_screen(stdscr, key)
                elif self.screen_mode == "exit":
                    self.running = False
                    break

                stdscr.refresh()
                time.sleep(0.1)
            except KeyboardInterrupt:
                self.running=False
                break
            except curses.error:
                # Ignorujemy ewentualne błędy curses (jeśli wychodzi poza ekran)
                pass

        self.close()

    # ---------------------
    # 1. Ekran Startowy
    # ---------------------
    def handle_start_screen(self, stdscr, key):
        stdscr.clear()

        # ASCII Art z zadania:
        ascii_logo = [
        r" ___  ___      _ _   _   _____                  _    ",
        r"|  \/  |     | | | (_) /  ___|                | |   ",
        r"| .  . |_   _| | |_ _  \ `--. _ __   ___ _   _| | __",
        r"| |\/| | | | | | __| |  `--. \ '_ \ / _ \ | | | |/ /",
        r"| |  | | |_| | | |_| | /\__/ / | | |  __/ |_| |   < ",
        r"\_|  |_/\__,_|_|\__|_| \____/|_| |_|\___|\__, |_|\_\\"
        ]
        row = 0
        for line in ascii_logo:
            try:
                stdscr.addstr(row, 2, line)
            except curses.error:
                pass
            row+=1

        row+=1
        # Menu
        try:
            stdscr.addstr(row, 4, "1) Rozpocznij gre")
            stdscr.addstr(row+2, 4, "2) Opis Gry")
            stdscr.addstr(row+4, 4, "3) Wyjdz")
        except curses.error:
            pass

        # Autorzy
        maxy, maxx = stdscr.getmaxyx()
        authors = "Paweł, Kuba, Adam"
        try:
            stdscr.addstr(maxy-1, 2, authors)
        except curses.error:
            pass

        # Obsługa klawiszy
        if key == ord('1'):
            # Rozpocznij grę
            self.connect_rabbit()
            if self.rabbit_connected:
                self.join_game()
                self.screen_mode = "game"
        elif key == ord('2'):
            # opis
            self.screen_mode = "description"
        elif key == ord('3'):
            # exit
            self.screen_mode = "exit"

    # ---------------------
    # 2. Ekran Opisu
    # ---------------------
    def handle_description_screen(self, stdscr, key):
        stdscr.clear()
        description_lines = [
            "Opis gry Multi-Sneyk:",
            "",
            "To niezwykle wciagająca gra w stylu retro,",
            "w której sterujesz wężem, zbierasz jabłka",
            "i unikasz kolizji. Dodatkowo musisz rywalizować",
            "z innymi graczami w czasie rzeczywistym!",
            "",
            "Sterowanie w stylu VIM: h/j/k/l. Zbierz 5 jabłek",
            "na każdej z 4 map, aby zostać mistrzem!",
        ]
        row=2
        for line in description_lines:
            try:
                stdscr.addstr(row, 2, line)
            except curses.error:
                pass
            row+=1

        try:
            stdscr.addstr(row+2, 2, "Wcisnij 'w' aby wrocic do menu startowego.")
        except curses.error:
            pass

        if key in [ord('w'), ord('W')]:
            self.screen_mode = "start"

    # ---------------------
    # 3. Ekran Gry
    # ---------------------
    def handle_game_screen(self, stdscr, key):
        if not self.rabbit_connected:
            # wracamy do start
            self.screen_mode = "start"
            return

        if key == ord('q'):
            self.screen_mode="exit"
            return
        elif key == ord('r'):
            self.send_restart()
        elif key in KEY_TO_DIRECTION:
            self.send_move(KEY_TO_DIRECTION[key])

        # Rysujemy stan gry:
        st = self.game_state
        if not st:
            try:
                stdscr.addstr(0,0,"Oczekiwanie na stan gry...")
            except curses.error:
                pass
            return

        gameOver = st.get("gameOver",False)
        winner = st.get("winner",None)
        if gameOver and winner:
            if winner==self.player_id:
                msg = "Gratulacje, jestes mistrzem sterowania VIMem"
            else:
                msg = "Leszcz"
            try:
                stdscr.addstr(0,0,msg)
            except curses.error:
                pass
            return

        current_room = st.get("current_room","")
        maps = st.get("maps",{})
        players = st.get("players",{})

        room_map = maps.get(current_room,[])
        for y, rowstr in enumerate(room_map):
            try:
                stdscr.addstr(y,0,rowstr)
            except curses.error:
                pass

        # Rysujemy węże
        for pid, pdata in players.items():
            if not pdata["alive"]:
                continue
            if pdata["room"]!=current_room:
                continue
            poss = pdata["positions"]
            lastDir = pdata.get("lastDir",None)
            for i,(py,px) in enumerate(poss):
                if i==0:
                    if lastDir in DIR_TO_HEAD:
                        c=DIR_TO_HEAD[lastDir]
                    else:
                        c='@'
                else:
                    c='s'
                try:
                    stdscr.addch(py,px,c)
                except curses.error:
                    pass

        info_y = len(room_map)+1
        try:
            stdscr.addstr(info_y,0,"Sterowanie: h/j/k/l, r=restart, q=wyjscie")
        except curses.error:
            pass

        # Ranking wg apples
        ranking = sorted(players.items(), key=lambda kv: kv[1].get("apples",0), reverse=True)
        offset=2
        for (rpid,rdata) in ranking:
            alive_str = "Alive" if rdata["alive"] else "Dead"
            app = rdata.get("apples",0)
            line = f"Gracz {rpid}: apples={app}, {alive_str}"
            try:
                stdscr.addstr(info_y+offset,0,line)
            except curses.error:
                pass
            offset+=1

    # ---------------------

    def close(self):
        self.running=False
        # Zatrzymaj nasłuch
        if hasattr(self,'consume_ch'):
            try:
                self.consume_ch.stop_consuming()
            except:
                pass
        if hasattr(self,'listen_thread') and self.listen_thread.is_alive():
            self.listen_thread.join()
        # Zamknij połączenia
        if hasattr(self,'publish_conn'):
            try:
                self.publish_conn.close()
            except:
                pass
        if hasattr(self,'consume_conn'):
            try:
                self.consume_conn.close()
            except:
                pass

        print(f"[CLIENT] Zakonczenie. (pid={self.player_id})")


def main():
    parser = argparse.ArgumentParser(description="Klient Multi Sneyk z ekranem startowym")
    parser.add_argument("--player_id", type=int, default=1)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--user", default="adminowiec")
    parser.add_argument("--password", default="Start123!")
    args = parser.parse_args()

    client = SnakeClient(args.player_id, args.host, args.user, args.password)
    if client.running:
        try:
            client.run_curses()
        except Exception as e:
            print(f"[ERROR] curses: {e}")
        finally:
            client.close()
    else:
        print("[CLIENT] Nie wystartował poprawnie.")


if __name__=="__main__":
    main()

