#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Klient gry Snake wieloosobowej.
Klawisz 'r' wysyła żądanie restartu gry do serwera,
który resetuje stan i ponownie dodaje wszystkie wcześniej podłączone player_id.

Po zjedzeniu jabłka wąż rośnie (obsługiwane po stronie serwera).
"""

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


class SnakeClient:
    def __init__(self, player_id, rabbitmq_host="localhost", rabbitmq_user="adminowiec", rabbitmq_pass=".p=o!v0cD5kK2+F3,{c1&DB"):
        self.player_id = str(player_id)
        self.running = True
        self.game_state = {}

        # Połączenie do publish
        try:
            self.publish_connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=rabbitmq_host,
                    port=5672,
                    virtual_host='/',
                    credentials=pika.PlainCredentials(rabbitmq_user, rabbitmq_pass)
                )
            )
            self.publish_channel = self.publish_connection.channel()
            self.server_queue = "server_queue"
            print("[CLIENT] Połączenie publish utworzone.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] Nie udało się połączyć z RabbitMQ do publish: {e}")
            self.running = False
            return

        # Połączenie do consume
        try:
            self.consume_connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=rabbitmq_host,
                    port=5672,
                    virtual_host='/',
                    credentials=pika.PlainCredentials(rabbitmq_user, rabbitmq_pass)
                )
            )
            self.consume_channel = self.consume_connection.channel()

            self.game_state_exchange = "game_state_exchange"
            self.consume_channel.exchange_declare(
                exchange=self.game_state_exchange,
                exchange_type='fanout'
            )

            result = self.consume_channel.queue_declare(queue='', exclusive=True)
            self.client_queue = result.method.queue
            self.consume_channel.queue_bind(
                exchange=self.game_state_exchange,
                queue=self.client_queue
            )
            print("[CLIENT] Połączenie consume utworzone.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] Nie udało się połączyć z RabbitMQ do consume: {e}")
            self.running = False
            return

        # Wątek odbioru
        self.listen_thread = threading.Thread(target=self.listen_game_state, daemon=True)
        self.listen_thread.start()

        # Dołączenie do gry
        self.join_game()

    def join_game(self):
        msg = {
            "type": "join_game",
            "player_id": self.player_id
        }
        self.send_to_server(msg)
        print(f"[CLIENT] Wysłano 'join_game' (Gracz {self.player_id}).")

    def send_move(self, direction):
        msg = {
            "type": "player_move",
            "player_id": self.player_id,
            "direction": direction
        }
        self.send_to_server(msg)

    def send_restart(self):
        msg = {
            "type": "restart_game",
            "player_id": self.player_id
        }
        self.send_to_server(msg)
        print("[CLIENT] Wysłano żądanie restartu gry.")

    def send_to_server(self, msg_dict):
        if not self.running:
            return
        try:
            self.publish_channel.basic_publish(
                exchange='',
                routing_key=self.server_queue,
                body=json.dumps(msg_dict)
            )
        except pika.exceptions.AMQPError as e:
            print(f"[ERROR] Nie udało się wysłać wiadomości: {e}")

    def listen_game_state(self):
        def callback(ch, method, properties, body):
            try:
                state = json.loads(body.decode("utf-8"))
                self.game_state = state
            except json.JSONDecodeError as e:
                print(f"[ERROR] Błąd dekodowania stanu gry: {e}")

        self.consume_channel.basic_consume(
            queue=self.client_queue,
            on_message_callback=callback,
            auto_ack=True
        )

        try:
            self.consume_channel.start_consuming()
        except pika.exceptions.AMQPError as e:
            print(f"[ERROR] Błąd w listen_game_state: {e}")
        except Exception as e:
            print(f"[ERROR] Niespodziewany błąd w listen_game_state: {e}")
        finally:
            self.running = False

    def run_curses(self):
        curses.wrapper(self.curses_loop)

    def curses_loop(self, stdscr):
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.clear()

        while self.running:
            try:
                key = stdscr.getch()
                if key == ord('q'):
                    self.running = False
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
                self.running = False
                break

        self.close()

    def draw_game(self, stdscr):
        if not self.game_state:
            stdscr.addstr(0, 0, "Oczekiwanie na dane z serwera...")
            return

        current_room = self.game_state.get("current_room", "room0")
        maps = self.game_state.get("maps", {})
        players = self.game_state.get("players", {})

        room_map = maps.get(current_room, [])
        for y, row in enumerate(room_map):
            try:
                stdscr.addstr(y, 0, row)
            except curses.error:
                pass

        # Rysujemy węże
        for pid, pdata in players.items():
            if not pdata["alive"]:
                continue
            if pdata["room"] != current_room:
                continue
            for i, (py, px) in enumerate(pdata["positions"]):
                c = '@' if i == 0 else 's'
                try:
                    stdscr.addch(py, px, c)
                except curses.error:
                    pass

        info_y = len(room_map) + 1
        try:
            stdscr.addstr(info_y, 0, f"Pokój: {current_room}")
            stdscr.addstr(info_y + 1, 0, "Sterowanie: h/j/k/l, r=restart, q=wyjście")

            # Lista graczy
            alive_pids = list(players.keys())
            stdscr.addstr(info_y + 2, 0, f"Aktualni gracze: {', '.join(alive_pids)}")

            if self.player_id in players:
                pinfo = players[self.player_id]
                alive_str = "Alive" if pinfo["alive"] else "Dead"
                stdscr.addstr(info_y + 3, 0, f"Twój stan (Gracz {self.player_id}): {alive_str}")
        except curses.error:
            pass

    def close(self):
        self.running = False
        try:
            self.consume_channel.stop_consuming()
        except:
            pass

        if self.listen_thread.is_alive():
            self.listen_thread.join()

        try:
            self.publish_connection.close()
        except:
            pass
        try:
            self.consume_connection.close()
        except:
            pass

        print(f"[CLIENT] Zamknięto klienta (player_id={self.player_id}).")


def main():
    parser = argparse.ArgumentParser(description="Klient Snake Multiplayer")
    parser.add_argument("--player_id", type=int, default=1, help="Identyfikator gracza, np. 1.")
    parser.add_argument("--host", type=str, default="localhost", help="Host RabbitMQ (IP/hostname)")
    parser.add_argument("--user", type=str, default="adminowiec", help="Użytkownik RabbitMQ")
    parser.add_argument("--password", type=str, default=".p=o!v0cD5kK2+F3,{c1&DB", help="Hasło RabbitMQ")
    args = parser.parse_args()

    client = SnakeClient(
        player_id=args.player_id,
        rabbitmq_host=args.host,
        rabbitmq_user=args.user,
        rabbitmq_pass=args.password
    )

    if client.running:
        try:
            client.run_curses()
        except Exception as e:
            print(f"[ERROR] Błąd curses: {e}")
        finally:
            client.close()
    else:
        print("[CLIENT] Klient nie wystartował poprawnie.")


if __name__ == "__main__":
    main()
