#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import threading
import time
import curses
import pika

# Zdefiniuj stałe, bo używasz ich w kliencie:
WALL = '#'
APPLE = 'O'

# Zdefiniuj słownik, który mapuje ostatni ruch węża (lastDir) na znak głowy
DIR_TO_HEADCHAR = {
    'k': '^',  # up
    'j': 'v',  # down
    'h': '<',  # left
    'l': '>'   # right
}

# Mapa klawiszy curses -> styl vim
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

        # Ustanowienie połączenia do publikowania
        try:
            self.pub_conn = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=host, port=5672, virtual_host='/',
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

        # Ustanowienie połączenia do konsumowania (odbieranie stanu gry)
        try:
            self.con_conn = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=host, port=5672, virtual_host='/',
                    credentials=pika.PlainCredentials(user, password)
                )
            )
            self.con_ch = self.con_conn.channel()
            self.game_state_exchange = "game_state_exchange"
            self.con_ch.exchange_declare(exchange=self.game_state_exchange, exchange_type='fanout')

            result = self.con_ch.queue_declare(queue='', exclusive=True)
            self.client_queue = result.method.queue
            self.con_ch.queue_bind(exchange=self.game_state_exchange, queue=self.client_queue)

            print("[CLIENT] Połączenie consume OK.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] consume connect fail: {e}")
            self.running = False
            return

        # Wątek nasłuchiwania stanu gry
        self.listen_thread = threading.Thread(target=self.listen_loop, daemon=True)
        self.listen_thread.start()

        # Dołącz do gry
        self.join_game()

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
        """
        Odbieranie stanu gry w pętli blocking.
        """
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
        """
        Uruchamia curses.wrapper z naszą pętlą.
        """
        curses.wrapper(self.curses_loop)

    def curses_loop(self, stdscr):
        """
        Logika curses + inicjalizacja kolorów.
        """
        curses.curs_set(0)
        stdscr.nodelay(True)

        # Inicjalizacja kolorów
        curses.start_color()
        # Ustaw pary kolorów (nr, fg, bg)
        # 1 -> zielony wąż
        curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
        # 2 -> czerwone ściany (#)
        curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)
        # 3 -> białe kropki ('.')
        curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_BLACK)
        # 4 - > zolte jablka ('O')
        curses.init_pair(4, curses.COLOR_YELLOW, curses.COLOR_BLACK)

        while self.running:
            try:
                key = stdscr.getch()
                if key == ord('q'):
                    self.running = False
                    break
                elif key == ord('r'):
                    # globalny restart
                    msg = {
                        "type": "restart_game",
                        "player_id": self.player_id
                    }
                    self.send_to_server(msg)
                elif key in KEY_TO_DIRECTION:
                    direction = KEY_TO_DIRECTION[key]
                    msg = {
                        "type": "player_move",
                        "player_id": self.player_id,
                        "direction": direction
                    }
                    self.send_to_server(msg)

                stdscr.clear()
                self.draw_game(stdscr)
                stdscr.refresh()

                time.sleep(0.1)
            except KeyboardInterrupt:
                self.running = False
                break

        self.close()

    def draw_game(self, stdscr):
        st = self.game_state
        if not st:
            stdscr.addstr(0, 0, "Oczekiwanie na dane z serwera...")
            return

        gameOver = st.get("gameOver", False)
        winner = st.get("winner", None)

        if gameOver and winner:
            # Gra zakończona
            if winner == self.player_id:
                stdscr.addstr(0, 0, "Gratulacje, jestes mistrzem sterowania VIMem", curses.A_BOLD)
            else:
                stdscr.addstr(0, 0, "Leszcz", curses.A_BOLD)
            return

        current_room = st.get("current_room", "")
        maps = st.get("maps", {})
        players = st.get("players", {})

        room_map = maps.get(current_room, [])

        # Rysowanie mapy z kolorami
        for y, row_str in enumerate(room_map):
            for x, ch in enumerate(row_str):
                if ch == WALL:
                    # ściana # -> kolor czerwony (pair=2)
                    stdscr.addch(y, x, ch, curses.color_pair(2))
                elif ch == '.':
                    # kropka -> kolor biały (pair=3)
                    stdscr.addch(y, x, ch, curses.color_pair(3))
                elif ch == 'O':
                    # jabłko -> kolor żółty (pair=4)
                    stdscr.addch(y, x, ch, curses.color_pair(4))
                else:
                    # pozostałe znaki w domyślnym kolorze
                    stdscr.addch(y, x, ch)

        # Rysujemy węże (w kolorze zielonym)
        for pid, pdata in players.items():
            if not pdata["alive"]:
                continue
            if pdata["room"] != current_room:
                continue

            for i, (py, px) in enumerate(pdata["positions"]):
                if i == 0:
                    # głowa
                    lastDir = pdata.get("lastDir", None)
                    head_char = DIR_TO_HEADCHAR.get(lastDir, '@')
                    # zielony
                    stdscr.addch(py, px, head_char, curses.color_pair(1) | curses.A_BOLD)
                else:
                    # ciało węża -> 's' zielony
                    stdscr.addch(py, px, 's', curses.color_pair(1))

        info_y = len(room_map) + 1
        stdscr.addstr(info_y, 0, f"Pokój: {current_room} (Sterowanie: h/j/k/l, r=restart, q=wyjście)")

        # Możesz dodać np. ranking, info, itp. 
        # Na przykład, jeśli w serwerze p["apples"] gromadzisz liczbę jabłek:
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
    parser = argparse.ArgumentParser(description="Kolorowy Klient Snake")
    parser.add_argument("--player_id", type=int, default=1)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--user", default="adminowiec")
    parser.add_argument("--password", default="Start123!")
    args = parser.parse_args()

    cl = SnakeClient(
        player_id=args.player_id,
        host=args.host,
        user=args.user,
        password=args.password
    )
    if cl.running:
        try:
            cl.run_curses()
        except Exception as e:
            print(f"[ERROR] curses: {e}")
        finally:
            cl.close()
    else:
        print("[CLIENT] Nie wystartował poprawnie.")


if __name__ == "__main__":
    main()
