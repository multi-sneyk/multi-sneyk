#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Klient wieloosobowej gry Snake z użyciem RabbitMQ.
Używa dwóch połączeń:
 - Jedno do wysyłania (publish) ruchów do serwera.
 - Drugie do odbierania (consume) stanu gry w wątku.

Sterowanie:
  - h: lewo
  - j: dół
  - k: góra
  - l: prawo
  - q: wyjście

Autor: ChatGPT (z poprawioną strukturą).
"""

import argparse
import json
import threading
import time
import curses  # pip install windows-curses na Windows
import pika

# Mapowanie klawiszy curses -> klawisze w stylu vim
KEY_TO_DIRECTION = {
    ord('h'): 'h',
    ord('j'): 'j',
    ord('k'): 'k',
    ord('l'): 'l'
}


class SnakeClient:
    def __init__(self, player_id):
        self.player_id = str(player_id)
        self.running = True
        self.game_state = {}  # ostatnio odebrany stan gry

        # ------------------------------
        # Połączenie do PUBLIKOWANIA (wysyłanie do serwera)
        # ------------------------------
        try:
            self.publish_connection = pika.BlockingConnection(
                pika.ConnectionParameters(host='localhost')
            )
            self.publish_channel = self.publish_connection.channel()
            self.server_queue = "server_queue"
            print("[CLIENT] Połączenie publish utworzone.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] Nie udało się połączyć z RabbitMQ do publish: {e}")
            self.running = False
            return

        # ------------------------------
        # Połączenie do KONSUMOWANIA (odbiór stanu gry z fanout)
        # ------------------------------
        try:
            self.consume_connection = pika.BlockingConnection(
                pika.ConnectionParameters(host='localhost')
            )
            self.consume_channel = self.consume_connection.channel()

            self.game_state_exchange = "game_state_exchange"
            # Deklarujemy wymianę fanout (powinno się zgadzać z serwerem)
            self.consume_channel.exchange_declare(
                exchange=self.game_state_exchange,
                exchange_type='fanout'
            )

            # Tworzymy tymczasową kolejkę do odbierania stanu gry
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

        # Uruchamiamy wątek do odbierania stanu gry
        self.listen_thread = threading.Thread(target=self.listen_game_state, daemon=True)
        self.listen_thread.start()

        # Dołączenie do gry
        self.join_game()

    def join_game(self):
        """
        Wysyła do serwera prośbę "join_game" z naszym player_id.
        """
        message = {
            "type": "join_game",
            "player_id": self.player_id
        }
        self.send_to_server(message)
        print(f"[CLIENT] Wysłano 'join_game' dla gracza {self.player_id}.")

    def send_move(self, direction):
        """
        Wysyła wiadomość "player_move" do serwera z kierunkiem.
        """
        message = {
            "type": "player_move",
            "player_id": self.player_id,
            "direction": direction
        }
        self.send_to_server(message)
        print(f"[CLIENT] Wysłano ruch {direction} dla gracza {self.player_id}.")

    def send_to_server(self, data_dict):
        """
        Publikuje dowolną wiadomość (JSON) do kolejki serwera.
        """
        if not self.running:
            return
        try:
            self.publish_channel.basic_publish(
                exchange='',
                routing_key=self.server_queue,
                body=json.dumps(data_dict)
            )
        except pika.exceptions.AMQPError as e:
            print(f"[ERROR] Nie udało się wysłać wiadomości: {e}")

    def listen_game_state(self):
        """
        Wątek odbierający stan gry z wymiany 'game_state_exchange'.
        Blokująco: start_consuming() lub .process_data_events().
        """

        def callback(ch, method, properties, body):
            try:
                state = json.loads(body.decode("utf-8"))
                self.game_state = state
            except json.JSONDecodeError as e:
                print(f"[ERROR] Błąd w dekodowaniu stanu gry: {e}")

        self.consume_channel.basic_consume(
            queue=self.client_queue,
            on_message_callback=callback,
            auto_ack=True
        )

        # pętla odbierająca wiadomości
        try:
            self.consume_channel.start_consuming()
        except pika.exceptions.AMQPError as e:
            print(f"[ERROR] Błąd w listen_game_state: {e}")
        except Exception as e:
            print(f"[ERROR] Niespodziewany błąd w listen_game_state: {e}")
        finally:
            self.running = False

    def run_curses(self):
        """
        Uruchamia interfejs tekstowy w curses, w którym można sterować wężem.
        """
        curses.wrapper(self.curses_loop)

    def curses_loop(self, stdscr):
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.clear()

        while self.running:
            try:
                key = stdscr.getch()
                if key == ord('q'):
                    # wyjście
                    self.running = False
                    break
                elif key in KEY_TO_DIRECTION:
                    direction = KEY_TO_DIRECTION[key]
                    self.send_move(direction)

                # Rysowanie stanu gry
                stdscr.clear()
                self.draw_game(stdscr)
                stdscr.refresh()
                time.sleep(0.1)
            except KeyboardInterrupt:
                break

        self.close()

    def draw_game(self, stdscr):
        """
        Rysuje aktualny stan gry w terminalu (curses).
        """
        if not self.game_state:
            stdscr.addstr(0, 0, "Oczekiwanie na stan gry z serwera...")
            return

        current_room = self.game_state.get("current_room", "room0")
        maps = self.game_state.get("maps", {})
        players = self.game_state.get("players", {})

        # Wyświetlamy mapę 'current_room'
        room_map = maps.get(current_room, [])
        for y, row in enumerate(room_map):
            try:
                stdscr.addstr(y, 0, row)
            except curses.error:
                pass

        # Rysujemy węże (tylko te w tym samym pokoju)
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

        # Informacje
        try:
            stdscr.addstr(len(room_map) + 1, 0, f"Pokój: {current_room}")
            stdscr.addstr(len(room_map) + 2, 0, "Sterowanie: h, j, k, l | q=wyjście")
            if self.player_id in players:
                alive_str = "Alive" if players[self.player_id]["alive"] else "Dead"
                stdscr.addstr(len(room_map) + 3, 0, f"Gracz {self.player_id}, status: {alive_str}")
        except curses.error:
            pass

    def close(self):
        """
        Zamyka klienta: kończy pętlę, zatrzymuje wątek i zamyka połączenia z RabbitMQ.
        """
        self.running = False
        # Zatrzymaj start_consuming
        try:
            self.consume_channel.stop_consuming()
        except:
            pass

        if self.listen_thread.is_alive():
            self.listen_thread.join()

        # Zamknij połączenia
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
    parser.add_argument("--player_id", type=int, required=True, help="Identyfikator gracza (np. 1)")
    args = parser.parse_args()

    client = SnakeClient(args.player_id)
    if client.running:
        try:
            client.run_curses()
        except Exception as e:
            print(f"[ERROR] Błąd w curses: {e}")
        finally:
            client.close()
    else:
        print("[CLIENT] Klient nie wystartował poprawnie (problem z połączeniami).")


if __name__ == "__main__":
    main()
