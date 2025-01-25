#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Prosty klient gry Snake wieloosobowej. 
Łączy się z serwerem RabbitMQ i odbiera zaktualizowany stan gry.
Wyświetla stan w terminalu (TUI przy użyciu curses).
Wysyła ruchy gracza (VIM-style: h, j, k, l).
"""

import argparse
import json
import threading
import time
import curses  # na Windows wymaga: pip install windows-curses
import pika

DIRECTIONS = ['h', 'j', 'k', 'l']  # do obsługi klawiszy vim
KEY_TO_DIRECTION = {
    ord('h'): 'h',
    ord('j'): 'j',
    ord('k'): 'k',
    ord('l'): 'l'
}

class SnakeClient:
    def __init__(self, player_id):
        self.player_id = str(player_id)
        self.connection = pika.BlockingConnection(pika.ConnectionParameters(host='localhost'))
        self.channel = self.connection.channel()

        # Kolejka serwera
        self.server_queue = "server_queue"

        # Exchange stanu gry
        self.game_state_exchange = "game_state_exchange"
        self.channel.exchange_declare(exchange=self.game_state_exchange, exchange_type='fanout')

        # Tworzymy tymczasową kolejkę do odbierania stanu gry
        result = self.channel.queue_declare(queue='', exclusive=True)
        self.client_queue = result.method.queue

        # Bindujemy tymczasową kolejkę do exchange
        self.channel.queue_bind(exchange=self.game_state_exchange, queue=self.client_queue)

        self.game_state = {}
        self.running = True

        # Uruchamiamy wątek do nasłuchiwania wiadomości o stanie gry
        self.listen_thread = threading.Thread(target=self.listen_game_state)
        self.listen_thread.start()

        # Dołączenie do gry
        self.join_game()

    def join_game(self):
        """
        Wysyła do serwera prośbę o dołączenie do gry.
        """
        message = {
            "type": "join_game",
            "player_id": self.player_id
        }
        self.channel.basic_publish(
            exchange='',
            routing_key=self.server_queue,
            body=json.dumps(message)
        )

    def send_move(self, direction):
        """
        Wysyła wiadomość o ruchu gracza do serwera.
        """
        message = {
            "type": "player_move",
            "player_id": self.player_id,
            "direction": direction
        }
        self.channel.basic_publish(
            exchange='',
            routing_key=self.server_queue,
            body=json.dumps(message)
        )

    def listen_game_state(self):
        """
        Odbiera asynchronicznie stan gry z exchange i aktualizuje lokalną zmienną game_state.
        """
        def callback(ch, method, properties, body):
            state = json.loads(body.decode("utf-8"))
            self.game_state = state

        self.channel.basic_consume(
            queue=self.client_queue,
            on_message_callback=callback,
            auto_ack=True
        )

        while self.running:
            try:
                self.connection.process_data_events(time_limit=1)
            except pika.exceptions.StreamLostError:
                break

    def close(self):
        self.running = False
        self.listen_thread.join()
        self.connection.close()

    def run_curses(self):
        """
        Główna metoda uruchamiająca tryb curses.
        """
        curses.wrapper(self.curses_loop)

    def curses_loop(self, stdscr):
        # Ustawienia początkowe curses
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.clear()

        while self.running:
            key = stdscr.getch()
            if key == ord('q'):
                # Wyjście z gry
                self.running = False
                break
            elif key in KEY_TO_DIRECTION:
                # Wysyłamy kierunek do serwera
                self.send_move(KEY_TO_DIRECTION[key])

            stdscr.clear()
            self.draw_game(stdscr)
            stdscr.refresh()
            time.sleep(0.1)

        self.close()

    def draw_game(self, stdscr):
        """
        Rysuje stan gry w oknie curses.
        """
        state = self.game_state
        if not state:
            stdscr.addstr(0, 0, "Oczekiwanie na dane z serwera...")
            return

        current_room = state.get("current_room", "room0")
        maps = state.get("maps", {})
        players = state.get("players", {})

        # Wyświetlamy aktualną mapę
        room_map = maps.get(current_room, [])
        for y, row in enumerate(room_map):
            stdscr.addstr(y, 0, row)

        # Rysujemy węże wszystkich graczy (tylko w tych pokojach, w których się znajdują)
        for pid, pdata in players.items():
            if not pdata["alive"]:
                continue
            if pdata["room"] != current_room:
                continue
            # Rysujemy segmenty węża
            for i, (py, px) in enumerate(pdata["positions"]):
                if i == 0:
                    char = '@'  # głowa węża
                else:
                    char = 's'
                try:
                    stdscr.addch(py, px, char)
                except:
                    # W razie problemu z rysowaniem (np. wyjście poza ekran)
                    pass

        stdscr.addstr(len(room_map) + 1, 0, f"Pokój: {current_room}")
        stdscr.addstr(len(room_map) + 2, 0, "Sterowanie: h(lewo), j(dół), k(góra), l(prawo), q(wyjście)")

def main():
    parser = argparse.ArgumentParser(description="Klient Snake Multiplayer")
    parser.add_argument("--player_id", type=int, default=1, help="Identyfikator gracza (np. 1)")
    args = parser.parse_args()

    client = SnakeClient(args.player_id)
    try:
        client.run_curses()
    finally:
        client.close()

if __name__ == "__main__":
    main()
