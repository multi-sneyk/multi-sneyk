#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import threading
import time
import curses
import pika

KEY_TO_DIRECTION = {
    ord('h'): 'h',
    ord('j'): 'j',
    ord('k'): 'k',
    ord('l'): 'l'
}

DIR_TO_HEAD = {
    'k': '^',
    'j': 'v',
    'h': '<',
    'l': '>'
}

class SnakeClient:
    def __init__(self, player_id, host="localhost", user="adminowiec", password="Start123!"):
        self.player_id = str(player_id)
        self.host = host
        self.user = user
        self.password = password

        self.running = True
        self.game_state = {}

        # Połączenie do publish
        try:
            self.publish_conn = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=self.host, port=5672, virtual_host='/',
                    credentials=pika.PlainCredentials(self.user, self.password)
                )
            )
            self.publish_ch = self.publish_conn.channel()
            self.server_queue = "server_queue"
            print("[CLIENT] publish connect OK.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] Publish connect fail: {e}")
            self.running=False
            return

        # Połączenie do consume
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

            print("[CLIENT] consume connect OK.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] consume connect fail: {e}")
            self.running=False
            return

        self.listen_thread = threading.Thread(target=self.listen_loop, daemon=True)
        self.listen_thread.start()

        # Wyślij join_game
        self.join_game()

    def join_game(self):
        msg = {
            "type": "join_game",
            "player_id": self.player_id
        }
        self.send_to_server(msg)
        print(f"[CLIENT] Wysłano join_game pid={self.player_id}")

    def send_to_server(self, data):
        if not self.running:
            return
        try:
            self.publish_ch.basic_publish(
                exchange='',
                routing_key=self.server_queue,
                body=json.dumps(data)
            )
        except pika.exceptions.AMQPError as e:
            print(f"[ERROR] publish msg: {e}")

    def send_move(self, direction):
        msg = {
            "type": "player_move",
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
        print("[CLIENT] global restart -> map0")

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

    def run_curses(self):
        curses.wrapper(self.curses_loop)

    def curses_loop(self, stdscr):
        curses.curs_set(0)
        stdscr.nodelay(True)

        while self.running:
            try:
                key = stdscr.getch()
                if key == ord('q'):
                    self.running=False
                    break
                elif key == ord('r'):
                    self.send_restart()
                elif key in KEY_TO_DIRECTION:
                    self.send_move(KEY_TO_DIRECTION[key])

                stdscr.clear()
                self.draw_game(stdscr)
                stdscr.refresh()

                time.sleep(0.1)
            except KeyboardInterrupt:
                self.running=False
                break
            except curses.error:
                # Ignorujemy ewentualne błędy curses
                pass

        self.close()

    def draw_game(self, stdscr):
        # Bezpieczne rysowanie: zawsze w 'try: ... except curses.error: pass'
        st = self.game_state
        if not st:
            try:
                stdscr.addstr(0,0,"Oczekiwanie na dane z serwera...")
            except curses.error:
                pass
            return

        gameOver = st.get("gameOver",False)
        winner = st.get("winner",None)
        if gameOver and winner:
            # Koniec
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
        # Rysujemy mapę - w pętli
        for y, rowstr in enumerate(room_map):
            try:
                stdscr.addstr(y,0,rowstr)
            except curses.error:
                pass

        # Rysujemy węże
        for pid,pdata in players.items():
            if not pdata["alive"]:
                continue
            if pdata["room"] != current_room:
                continue
            positions = pdata["positions"]
            lDir = pdata.get("lastDir",None)
            for i,(py,px) in enumerate(positions):
                if i==0:
                    # głowa
                    if lDir in DIR_TO_HEAD:
                        c=DIR_TO_HEAD[lDir]
                    else:
                        c='@'
                else:
                    c='s'
                try:
                    stdscr.addch(py, px, c)
                except curses.error:
                    pass

        # Wiadomości o sterowaniu etc.
        info_y = len(room_map)+1
        try:
            stdscr.addstr(info_y,0,"Sterowanie: h/j/k/l, r=restart, q=wyjście")
        except curses.error:
            pass

        # Ranking: sortujemy wg apples malejąco
        ranking = sorted(players.items(), key=lambda kv: kv[1].get("apples",0), reverse=True)
        offset=2
        for (rpid,rdata) in ranking:
            alive_str = "Alive" if rdata["alive"] else "Dead"
            apples = rdata.get("apples",0)
            txt = f"Gracz {rpid}: apples={apples}, {alive_str}"
            try:
                stdscr.addstr(info_y+offset, 0, txt)
            except curses.error:
                pass
            offset+=1

    def close(self):
        self.running=False
        try:
            self.consume_ch.stop_consuming()
        except:
            pass
        if hasattr(self,'listen_thread') and self.listen_thread.is_alive():
            self.listen_thread.join()

        try:
            self.publish_conn.close()
        except:
            pass
        try:
            self.consume_conn.close()
        except:
            pass
        print(f"[CLIENT] Zakończono działanie (pid={self.player_id}).")


def main():
    parser = argparse.ArgumentParser("Klient Multi-Sneyk - minimalny ignoring curses errors")
    parser.add_argument("--player_id", type=int, default=1)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--user", default="adminowiec")
    parser.add_argument("--password", default="Start123!")
    args = parser.parse_args()

    cl = SnakeClient(args.player_id, args.host, args.user, args.password)
    if cl.running:
        try:
            cl.run_curses()
        except Exception as e:
            print(f"[ERROR] curses: {e}")
        finally:
            cl.close()
    else:
        print("[CLIENT] Nie wystartował poprawnie.")


if __name__=="__main__":
    main()
