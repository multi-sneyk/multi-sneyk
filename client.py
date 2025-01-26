#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import threading
import curses
import pika
import sys
from start_screen import show_start_screen, show_description

WALL = '#'
APPLE = 'O'

DIR_TO_HEADCHAR = {
    'k': '^',
    'j': 'v',
    'h': '<',
    'l': '>'
}

KEY_TO_DIRECTION = {
    ord('h'): 'h',
    ord('j'): 'j',
    ord('k'): 'k',
    ord('l'): 'l'
}

class SnakeClient:
    def __init__(self, player_id, host="localhost", user="adminowiec", password=".p=o!v0cD5kK2+F3,{c1&DB"):
        self.player_id = str(player_id)
        self.running = True
        self.game_state = {}

        # Połączenie -> publikowanie
        try:
            self.pub_conn = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=host,
                    port=5672,
                    virtual_host='/',
                    credentials=pika.PlainCredentials(user, password)
                )
            )
            self.pub_ch = self.pub_conn.channel()
            self.server_queue = "server_queue"
            print("[CLIENT] Połączenie publish OK.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] Publish connect fail: {e}")
            self.running = False
            return

        # Połączenie -> konsumowanie
        try:
            self.con_conn = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=host,
                    port=5672,
                    virtual_host='/',
                    credentials=pika.PlainCredentials(user, password)
                )
            )
            self.con_ch = self.con_conn.channel()
            self.game_state_exchange = "game_state_exchange"
            self.con_ch.exchange_declare(exchange=self.game_state_exchange, exchange_type='fanout')

            result = self.con_ch.queue_declare(queue='', exclusive=True)
            self.client_queue = result.method.queue
            self.con_ch.queue_bind(
                exchange=self.game_state_exchange,
                queue=self.client_queue
            )
            print("[CLIENT] Połączenie consume OK.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] consume connect fail: {e}")
            self.running = False
            return

        self.listen_thread = threading.Thread(target=self.listen_loop, daemon=True)
        self.listen_thread.start()

    def join_game(self):
        msg = {
            "type": "join_game",
            "player_id": self.player_id
        }
        self.send_to_server(msg)
        print(f"[CLIENT] Wysłano join_game (pid={self.player_id}).")

    def send_to_server(self, data):
        if not self.running:
            return
        try:
            self.pub_ch.basic_publish(
                exchange='',
                routing_key=self.server_queue,
                body=json.dumps(data)
            )
        except pika.exceptions.AMQPError as e:
            print(f"[ERROR] send_to_server: {e}")

    def listen_loop(self):
        def callback(ch, method, properties, body):
            try:
                state = json.loads(body.decode("utf-8"))
                self.game_state = state
            except json.JSONDecodeError:
                pass

        self.con_ch.basic_consume(
            queue=self.client_queue,
            on_message_callback=callback,
            auto_ack=True
        )
        try:
            self.con_ch.start_consuming()
        except:
            pass
        self.running = False

    def run_curses(self):
        curses.wrapper(self.curses_loop)

    def curses_loop(self, stdscr):
        curses.curs_set(0)
        # UWAGA: nodelay(False) -> czekamy na klawisz
        stdscr.nodelay(False)

        # Inicjalizacja kolorów
        curses.start_color()
        curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)  # wąż
        curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)    # ściany
        curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_BLACK)  # kropki
        curses.init_pair(4, curses.COLOR_YELLOW, curses.COLOR_BLACK) # jabłka

        # Dołącz do gry (wysyłamy join_game)
        self.join_game()

        while self.running:
            key = stdscr.getch()
            if key == ord('q'):
                self.running = False
                break
            elif key == ord('r'):
                msg = {
                    "type": "restart_game",
                    "player_id": self.player_id
                }
                self.send_to_server(msg)
            elif key in KEY_TO_DIRECTION:
                direction = KEY_TO_DIRECTION[key]
                self.send_to_server({
                    "type": "player_move",
                    "player_id": self.player_id,
                    "direction": direction
                })

            stdscr.clear()
            self.draw_game(stdscr)
            stdscr.refresh()

            # NIE robimy time.sleep(0.1), bo chcemy natychmiast reagować
            # i nodelay=False czeka na klawisz

        self.close()

    def draw_game(self, stdscr):
        if not self.game_state:
            stdscr.addstr(0, 0, "Oczekiwanie na dane z serwera...")
            return

        gameOver = self.game_state.get("gameOver", False)
        winner = self.game_state.get("winner", None)

        if gameOver and winner:
            if winner == self.player_id:
                stdscr.addstr(0, 0, "Gratulacje, jestes mistrzem sterowania VIMem", curses.A_BOLD)
            else:
                stdscr.addstr(0, 0, "Leszcz", curses.A_BOLD)
            return

        current_room = self.game_state.get("current_room", "")
        maps = self.game_state.get("maps", {})
        players = self.game_state.get("players", {})

        room_map = maps.get(current_room, [])

        # Rysowanie mapy
        for y, row_str in enumerate(room_map):
            for x, ch in enumerate(row_str):
                if ch == WALL:
                    stdscr.addch(y, x, ch, curses.color_pair(2))
                elif ch == '.':
                    stdscr.addch(y, x, ch, curses.color_pair(3))
                elif ch == 'O':
                    stdscr.addch(y, x, ch, curses.color_pair(4))
                else:
                    stdscr.addch(y, x, ch)

        # Rysowanie węży
        for pid, pdata in players.items():
            if not pdata["alive"]:
                continue
            if pdata["room"] != current_room:
                continue

            for i, (py, px) in enumerate(pdata["positions"]):
                if i == 0:
                    lastDir = pdata.get("lastDir", None)
                    head_char = DIR_TO_HEADCHAR.get(lastDir, '@')
                    stdscr.addch(py, px, head_char, curses.color_pair(1) | curses.A_BOLD)
                else:
                    stdscr.addch(py, px, 's', curses.color_pair(1))

        info_y = len(room_map) + 1
        stdscr.addstr(info_y, 0, f"Pokój: {current_room} (Sterowanie: h/j/k/l, r=restart, q=wyjście)")

        # Ranking
        ranking = sorted(players.items(), key=lambda kv: kv[1].get("apples", 0), reverse=True)
        line_offset = 2
        for (rpid, rdata) in ranking:
            apples = rdata.get("apples", 0)
            alive_str = "Alive" if rdata["alive"] else "Dead"
            stdscr.addstr(info_y + line_offset, 0, f"Gracz {rpid}: jabłka={apples}, {alive_str}")
            line_offset += 1

    def close(self):
        self.running = False
        try:
            self.con_ch.stop_consuming()
        except:
            pass
        if self.listen_thread.is_alive():
            self.listen_thread.join()

        try:
            self.pub_conn.close()
        except:
            pass
        try:
            self.con_conn.close()
        except:
            pass

        print(f"[CLIENT] Zamknięto klienta (pid={self.player_id}).")


def main():
    parser = argparse.ArgumentParser("Kolorowy Klient Snake + Ekran Startowy (bez podwójnego kliknięcia)")
    parser.add_argument("--player_id", type=int, default=1)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--user", default="adminowiec")
    parser.add_argument("--password", default=".p=o!v0cD5kK2+F3,{c1&DB")
    args = parser.parse_args()

    def start_menu_driver():
        while True:
            choice = curses.wrapper(show_start_screen)
            if choice == 1:
                return True
            elif choice == 2:
                curses.wrapper(show_description)
            elif choice == 3:
                return False

    # Ekran startowy
    start_choice = start_menu_driver()
    if not start_choice:
        print("[CLIENT] Wybrano 'Wyjdź z gry'. Koniec.")
        sys.exit(0)

    # Rozpocznij grę
    cl = SnakeClient(args.player_id, args.host, args.user, args.password)
    if cl.running:
        try:
            cl.run_curses()
        except Exception as e:
            print(f"[ERROR] curses: {e}")
        finally:
            cl.close()
    else:
        print("[CLIENT] Klient nie wystartował poprawnie.")


if __name__ == "__main__":
    main()
