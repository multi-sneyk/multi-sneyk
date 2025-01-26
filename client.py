#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import threading
import time
import curses
import pika
import sys

# Kierunki w stylu VIM
KEY_TO_DIRECTION = {
    ord('h'): 'h',
    ord('j'): 'j',
    ord('k'): 'k',
    ord('l'): 'l'
}

# Zamiana ostatniego kierunku na znak głowy
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

        # Czy jesteśmy w trybie "start-screen", "description", czy "game"?
        # Na start: "start-screen".
        self.screen_mode = "start"  # start, description, game, exit

        # Wątek i logika RabbitMQ tworzymy dopiero po wejściu w tryb "game",
        # ale często chcemy "join_game" od razu. W tym przykładzie
        # najpierw pokażemy menu, a dopiero przy "Rozpocznij grę" łączymy się z RabbitMQ.
        self.rabbit_connected = False

    def connect_rabbit(self):
        """
        Łączy się z RabbitMQ (publish i consume). Tworzy wątek nasłuchiwania.
        """
        if self.rabbit_connected:
            return
        try:
            self.publish_conn = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=self.host,
                    port=5672,
                    virtual_host='/',
                    credentials=pika.PlainCredentials(self.user, self.password)
                )
            )
            self.publish_ch = self.publish_conn.channel()
            self.server_queue = "server_queue"
            print("[CLIENT] Połączenie publish OK.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] Publish connect fail: {e}")
            self.running = False
            return

        try:
            self.consume_conn = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=self.host,
                    port=5672,
                    virtual_host='/',
                    credentials=pika.PlainCredentials(self.user, self.password)
                )
            )
            self.consume_ch = self.consume_conn.channel()
            self.game_state_exchange = "game_state_exchange"
            self.consume_ch.exchange_declare(exchange=self.game_state_exchange, exchange_type='fanout')

            result = self.consume_ch.queue_declare(queue='', exclusive=True)
            self.client_queue = result.method.queue
            self.consume_ch.queue_bind(exchange=self.game_state_exchange, queue=self.client_queue)

            print("[CLIENT] Połączenie consume OK.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] consume connect fail: {e}")
            self.running = False
            return

        self.listen_thread = threading.Thread(target=self.listen_loop, daemon=True)
        self.listen_thread.start()

        self.rabbit_connected = True

    def join_game(self):
        """
        Wysyła wiadomość join_game do serwera.
        """
        msg = {
            "type": "join_game",
            "player_id": self.player_id
        }
        self.send_to_server(msg)
        print(f"[CLIENT] Wysłano join_game (pid={self.player_id}).")

    def send_to_server(self, data):
        if not self.rabbit_connected:
            return
        try:
            self.publish_ch.basic_publish(
                exchange='',
                routing_key=self.server_queue,
                body=json.dumps(data)
            )
        except pika.exceptions.AMQPError as e:
            print(f"[ERROR] send_to_server: {e}")

    def send_move(self, direction):
        msg = {
            "type": "player_move",
            "player_id": self.player_id,
            "direction": direction
        }
        self.send_to_server(msg)

    def send_restart(self):
        """
        Globalny restart (wszystkich) - wraca do mapy 0
        """
        msg = {
            "type": "restart_game",
            "player_id": self.player_id
        }
        self.send_to_server(msg)
        print("[CLIENT] globalny restart => mapa 0")

    def listen_loop(self):
        def callback(ch, method, props, body):
            try:
                st = json.loads(body.decode("utf-8"))
                self.game_state = st
            except json.JSONDecodeError:
                pass

        self.consume_ch.basic_consume(
            queue=self.client_queue,
            on_message_callback=callback,
            auto_ack=True
        )
        try:
            self.consume_ch.start_consuming()
        except pika.exceptions.AMQPError as e:
            print(f"[ERROR] start_consuming: {e}")
        finally:
            self.running=False

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
                    # zakończ
                    self.running=False
                    break

                stdscr.refresh()
                time.sleep(0.1)
            except KeyboardInterrupt:
                self.running=False
                break

        self.close()

    # ---------------------
    # 1. Ekran startowy
    # ---------------------
    def handle_start_screen(self, stdscr, key):
        stdscr.clear()

        # Duży napis "Multi Sneyk" (np. ascii-art)
        # Można skorzystać z figlet, ale tu wkleimy prosty ASCII:
        multi_sneyk_ascii = [
"  __  __       _  _   _         ",
" |  \\/  |     (_)| | | |        ",
" | \\  / |  ___ _ | |_| |  ___   ",
" | |\\/| | / _ \\ || __| | / _ \\  ",
" | |  | ||  __/ || |_| || (_) | ",
" |_|  |_| \\___|_| \\__|_| \\___/  ",
"",
        ]

        row = 0
        for line in multi_sneyk_ascii:
            stdscr.addstr(row, 2, line)
            row+=1

        row+=1
        stdscr.addstr(row, 4, "1) Rozpocznij grę multiplayer")
        row+=2
        stdscr.addstr(row, 4, "2) Opis gry")
        row+=2
        stdscr.addstr(row, 4, "3) Wyjdź z gry")
        row+=2

        # Autorzy na dole
        maxy, maxx = stdscr.getmaxyx()
        authors = "Autor1, Autor2, Autor3"
        stdscr.addstr(maxy-1, 2, authors)

        # Obsługa klawiszy
        if key == ord('1'):
            # Rozpocznij grę
            # łączy się z Rabbit, dołącza do gry
            self.connect_rabbit()
            if self.rabbit_connected:
                self.join_game()
                self.screen_mode = "game"
        elif key == ord('2'):
            # przejdz do opisu gry
            self.screen_mode = "description"
        elif key == ord('3'):
            # wyjdz
            self.screen_mode = "exit"

    # ---------------------
    # 2. Ekran opisu gry
    # ---------------------
    def handle_description_screen(self, stdscr, key):
        stdscr.clear()
        # Wyświetlamy fabułę
        # Wymyślona fabuła:
        description_lines = [
            "Opis gry 'Multi Sneyk':",
            "",
            "Dawno, dawno temu w krainie wężowych wojowników...",
            "złowieszcza mgła spowiła pola jabłoni...",
            "Tylko najzręczniejsi mistrzowie VIM potrafią",
            "prowadzić węże do zwycięstwa...",
            "",
            "Waszym zadaniem jest zebrać 5 jabłek na każdej mapie,",
            "unikać kolizji i udowodnić, kto jest mistrzem sterowania!"
        ]
        row=2
        for line in description_lines:
            stdscr.addstr(row, 2, line)
            row+=1

        # Przycisk: "Wróć (w) do menu"
        stdscr.addstr(row+2, 2, "W - Wróć do menu startowego")

        # Klawisz
        if key in [ord('w'), ord('W')]:
            self.screen_mode = "start"

    # ---------------------
    # 3. Ekran właściwej gry
    # ---------------------
    def handle_game_screen(self, stdscr, key):
        if not self.rabbit_connected:
            # coś poszło nie tak, wracamy do startu
            self.screen_mode = "start"
            return

        # Obsługa klawiszy
        if key == ord('q'):
            self.screen_mode = "exit"
            return
        elif key == ord('r'):
            # globalny restart
            self.send_restart()
        elif key in KEY_TO_DIRECTION:
            self.send_move(KEY_TO_DIRECTION[key])

        # Rysujemy stan gry
        st = self.game_state
        if not st:
            stdscr.addstr(0,0,"Oczekiwanie na dane z serwera (game)...")
            return

        gameOver = st.get("gameOver", False)
        winner = st.get("winner", None)
        if gameOver and winner:
            # zakonczenie
            if winner==self.player_id:
                stdscr.addstr(0,0,"Gratulacje, jestes mistrzem sterowania VIMem")
            else:
                stdscr.addstr(0,0,"Leszcz")
            return

        current_room = st.get("current_room","")
        maps = st.get("maps",{})
        players = st.get("players",{})

        room_map = maps.get(current_room, [])
        for y, row_str in enumerate(room_map):
            stdscr.addstr(y,0,row_str)

        # Rysujemy węże
        # Wspomagamy się lastDir -> strzałka
        for pid,pdata in players.items():
            if not pdata["alive"]:
                continue
            if pdata["room"]!=current_room:
                continue
            poss = pdata["positions"]
            lDir = pdata.get("lastDir",None)
            for i,(py,px) in enumerate(poss):
                if i==0:
                    # głowa
                    if lDir in DIR_TO_HEAD:
                        c=DIR_TO_HEAD[lDir]
                    else:
                        c='@'
                else:
                    c='s'
                try:
                    stdscr.addch(py,px,c)
                except:
                    pass

        # Ranking wg "apples" (ile ma jabłek w tej mapie)
        # Sortujemy malejąco
        ranking = sorted(players.items(), key=lambda kv: kv[1]["apples"], reverse=True)

        info_y = len(room_map)+1
        stdscr.addstr(info_y,0, f"Mapa: {current_room}, r=restart, q=wyjście")

        line_offset=2
        for (rpid, rdata) in ranking:
            alive_str = "Alive" if rdata["alive"] else "Dead"
            apples = rdata["apples"]
            stdscr.addstr(info_y+line_offset,0,
                f"Gracz {rpid}: jabłka={apples}, {alive_str}")
            line_offset+=1

    # ---------------------

    def close(self):
        self.running=False
        if hasattr(self, 'listen_thread') and self.listen_thread.is_alive():
            try:
                self.consume_ch.stop_consuming()
            except:
                pass
            self.listen_thread.join()

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

        print(f"[CLIENT] Zakończono działanie. (pid={self.player_id})")


def main():
    parser = argparse.ArgumentParser(description="Klient Multi Sneyk z ekranem startowym")
    parser.add_argument("--player_id", type=int, default=1)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--user", default="adminowiec")
    parser.add_argument("--password", default="Start123!")
    args = parser.parse_args()

    client = SnakeClient(player_id=args.player_id,
                         host=args.host,
                         user=args.user,
                         password=args.password)
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

