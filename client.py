#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import threading
import time
import curses
import pika

DIR_TO_HEAD = {
    'k': '^',
    'j': 'v',
    'h': '<',
    'l': '>'
}

class SnakeClient:
    def __init__(self, player_id, host="localhost", user="adminowiec", password=".p=o!v0cD5kK2+F3,{c1&DB"):
        self.player_id = str(player_id)
        self.running = True
        self.game_state = {}

        try:
            self.pub_conn = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=host, port=5672, virtual_host='/',
                    credentials=pika.PlainCredentials(user,password)
                )
            )
            self.pub_ch = self.pub_conn.channel()
            self.server_queue = "server_queue"
            print("[CLIENT] publish connect ok.")
        except:
            print("[CLIENT] publish connect fail.")
            self.running=False
            return

        try:
            self.con_conn = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=host, port=5672, virtual_host='/',
                    credentials=pika.PlainCredentials(user,password)
                )
            )
            self.con_ch = self.con_conn.channel()
            self.game_state_exchange="game_state_exchange"
            self.con_ch.exchange_declare(exchange=self.game_state_exchange, exchange_type='fanout')

            result=self.con_ch.queue_declare(queue='', exclusive=True)
            self.client_queue = result.method.queue
            self.con_ch.queue_bind(exchange=self.game_state_exchange, queue=self.client_queue)
            print("[CLIENT] consume connect ok.")
        except:
            print("[CLIENT] consume connect fail.")
            self.running=False
            return

        self.listen_thread = threading.Thread(target=self.listen_loop, daemon=True)
        self.listen_thread.start()

        self.join_game()

    def join_game(self):
        msg = {
            "type":"join_game",
            "player_id": self.player_id
        }
        self.send_to_server(msg)
        print(f"[CLIENT] join_game -> pid={self.player_id}")

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
        print("[CLIENT] globalny restart do mapy0")

    def send_to_server(self, data):
        if not self.running:
            return
        try:
            self.pub_ch.basic_publish(
                exchange='',
                routing_key=self.server_queue,
                body=json.dumps(data)
            )
        except:
            pass

    def listen_loop(self):
        def callback(ch, method, properties, body):
            try:
                st = json.loads(body.decode("utf-8"))
                self.game_state = st
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
                elif key==ord('r'):
                    self.send_restart()
                elif key in [ord('h'), ord('j'), ord('k'), ord('l')]:
                    d = chr(key)
                    self.send_move(d)

                stdscr.clear()
                self.draw_game(stdscr)
                stdscr.refresh()

                time.sleep(0.1)
            except KeyboardInterrupt:
                self.running=False
                break

        self.close()

    def draw_game(self, stdscr):
        st = self.game_state
        if not st:
            stdscr.addstr(0,0,"Oczekiwanie na dane z serwera...")
            return

        gameOver = st.get("gameOver", False)
        winner = st.get("winner", None)
        if gameOver and winner:
            if winner==self.player_id:
                stdscr.addstr(0,0,"Gratulacje, jestes mistrzem sterowania VIMem")
            else:
                stdscr.addstr(0,0,"Leszcz")
            return

        current_room = st.get("current_room","")
        maps = st.get("maps",{})
        players = st.get("players",{})
        room_map = maps.get(current_room,[])
        for y, rowstr in enumerate(room_map):
            stdscr.addstr(y,0,rowstr)

        # rysujemy węże
        for pid,pdata in players.items():
            if not pdata["alive"]:
                continue
            if pdata["room"]!=current_room:
                continue
            poss = pdata["positions"]
            lastDir = pdata.get("lastDir",None)
            for i, (py,px) in enumerate(poss):
                if i==0:
                    # głowa
                    if lastDir in DIR_TO_HEAD:
                        c = DIR_TO_HEAD[lastDir]
                    else:
                        c = '@'
                else:
                    c='s'
                stdscr.addch(py,px,c)

        info_y = len(room_map)+1
        stdscr.addstr(info_y,0,f"Pokój: {current_room}")
        stdscr.addstr(info_y+1,0,"Sterowanie: h/j/k/l, r=global restart, q=wyjście")

        # zrobimy ranking: posortuj graczy wg apples malejąco
        # players[pid]["apples"]
        ranking = sorted(players.items(), key=lambda kv: kv[1]["apples"], reverse=True)

        line_offset=2
        for (rpid, rdata) in ranking:
            alive_str = "Alive" if rdata["alive"] else "Dead"
            apples = rdata["apples"]
            stdscr.addstr(info_y+line_offset,0,
                          f"{rpid}: apples={apples}, {alive_str}")
            line_offset+=1

    def close(self):
        self.running=False
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

        print(f"[CLIENT] Zamknięto klienta pid={self.player_id}.")


def main():
    parser = argparse.ArgumentParser("Klient Snake - 4 mapy po 5 punktów, globalny restart, ranking")
    parser.add_argument("--player_id", type=int, default=1)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--user", default="adminowiec")
    parser.add_argument("--password", default=".p=o!v0cD5kK2+F3,{c1&DB")
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
