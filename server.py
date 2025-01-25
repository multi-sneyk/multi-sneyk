#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Prosty serwer gry Snake wieloosobowej z użyciem RabbitMQ.
Zarządza stanem gry i rozsyła informacje do klientów.
"""

import threading
import time
import json
import pika
import os

# ----- Ustawienia gry -----
UPDATE_INTERVAL = 0.2  # co ile sekund aktualizujemy stan gry
MAX_PLAYERS = 3        # maksymalna liczba graczy (dla przykładu)

# ----- Pomocnicze stałe -----
WALL = '#'
APPLE = 'O'
EMPTY = '.'

# Kierunki ruchu (zgodne z vim-style)
DIRECTIONS = {
    'h': (0, -1),   # left
    'l': (0, 1),    # right
    'k': (-1, 0),   # up
    'j': (1, 0)     # down
}

class SnakeGame:
    def __init__(self, maps_folder="maps"):
        """
        Inicjalizuje grę, wczytując mapy z katalogu maps_folder.
        Przykładowo: room0.txt, room1.txt - możesz dodać więcej.
        """
        self.maps = {}
        self.load_maps(maps_folder)

        # Ustawiamy aktualny pokój na "room0"
        self.current_room = "room0"

        # Stan gry
        self.players = {}  # {player_id: {"positions": [...], "direction": (dx, dy), "alive": bool, "room": "room0"}}
        self.player_count = 0

        # Przyjęty rozmiar mapy (zakładamy, że wszystkie mapy mają ten sam rozmiar w tym przykładzie)
        self.height = len(self.maps[self.current_room])
        self.width = len(self.maps[self.current_room][0])

        # Blokada do synchronicznego dostępu
        self.lock = threading.Lock()

    def load_maps(self, folder):
        """
        Wczytuje wszystkie pliki tekstowe z katalogu maps (np. room0.txt, room1.txt)
        i zapisuje je w słowniku self.maps pod kluczem np. 'room0'.
        """
        for filename in os.listdir(folder):
            if filename.endswith(".txt"):
                room_name = filename.replace(".txt", "")
                with open(os.path.join(folder, filename), 'r') as f:
                    lines = [list(line.rstrip('\n')) for line in f]
                self.maps[room_name] = lines

    def add_player(self, player_id):
        """
        Dodaje nowego gracza do gry i inicjuje jego pozycję.
        """
        with self.lock:
            if self.player_count >= MAX_PLAYERS:
                return False  # nie dodajemy nowych graczy, jeśli osiągnięto limit

            # Znajdź wolne miejsce na mapie, np. na środku.
            start_y = self.height // 2 + self.player_count
            start_x = self.width // 2

            self.players[player_id] = {
                "positions": [(start_y, start_x)],  # wąż o długości 1
                "direction": (0, 0),   # na start stoi w miejscu
                "alive": True,
                "room": self.current_room
            }
            self.player_count += 1
            return True

    def update_player_direction(self, player_id, direction):
        """
        Aktualizuje kierunek ruchu gracza (jeśli gracz żyje).
        """
        with self.lock:
            if player_id in self.players and self.players[player_id]["alive"]:
                self.players[player_id]["direction"] = DIRECTIONS.get(direction, (0, 0))

    def update(self):
        """
        Główna pętla aktualizująca stan gry: ruch węży, kolizje, zbieranie jabłek,
        przechodzenie między pomieszczeniami, itp.
        """
        with self.lock:
            dead_players = []
            # Dla każdego gracza, wykonaj ruch
            for pid, pdata in self.players.items():
                if not pdata["alive"]:
                    continue
                # Oblicz nową głowę węża
                (dy, dx) = pdata["direction"]
                if (dy, dx) == (0, 0):
                    # gracz jeszcze nie ruszył
                    continue
                head_y, head_x = pdata["positions"][0]
                new_y = head_y + dy
                new_x = head_x + dx

                current_room = pdata["room"]
                # Sprawdź, czy gracz chce wyjść poza mapę (przejście do innego pokoju)
                if new_y < 0:
                    # przejście górne
                    new_room = self.get_adjacent_room(current_room, "up")
                    if new_room:
                        pdata["room"] = new_room
                        (new_y, new_x) = self.teleport_to_room_edge(new_room, "down", new_x)
                    else:
                        # brak pokoju powyżej -> kolizja ze ścianą
                        pdata["alive"] = False
                        dead_players.append(pid)
                        continue
                elif new_y >= self.height:
                    # przejście dolne
                    new_room = self.get_adjacent_room(current_room, "down")
                    if new_room:
                        pdata["room"] = new_room
                        (new_y, new_x) = self.teleport_to_room_edge(new_room, "up", new_x)
                    else:
                        pdata["alive"] = False
                        dead_players.append(pid)
                        continue
                elif new_x < 0:
                    # przejście lewe
                    new_room = self.get_adjacent_room(current_room, "left")
                    if new_room:
                        pdata["room"] = new_room
                        (new_y, new_x) = self.teleport_to_room_edge(new_room, "right", new_y)
                    else:
                        pdata["alive"] = False
                        dead_players.append(pid)
                        continue
                elif new_x >= self.width:
                    # przejście prawe
                    new_room = self.get_adjacent_room(current_room, "right")
                    if new_room:
                        pdata["room"] = new_room
                        (new_y, new_x) = self.teleport_to_room_edge(new_room, "left", new_y)
                    else:
                        pdata["alive"] = False
                        dead_players.append(pid)
                        continue

                # Jeżeli gracz w nowym pokoju to sprawdź kolizję w nowej mapie
                new_room_map = self.maps[pdata["room"]]
                if new_room_map[new_y][new_x] == WALL:
                    # kolizja ze ścianą
                    pdata["alive"] = False
                    dead_players.append(pid)
                    continue

                # Sprawdź kolizje z innymi wężami
                for other_pid, other_pdata in self.players.items():
                    if not other_pdata["alive"]:
                        continue
                    if other_pid == pid:
                        # kolizja z samym sobą
                        if (new_y, new_x) in other_pdata["positions"]:
                            pdata["alive"] = False
                            dead_players.append(pid)
                            break
                    else:
                        # kolizja z innym wężem
                        if pdata["room"] == other_pdata["room"] and (new_y, new_x) in other_pdata["positions"]:
                            pdata["alive"] = False
                            dead_players.append(pid)
                            break

                if pid in dead_players:
                    continue

                # Jeżeli żyje, przesuń węża
                pdata["positions"].insert(0, (new_y, new_x))

                # Sprawdź, czy zjedzono jabłko
                if new_room_map[new_y][new_x] == APPLE:
                    # wąż rośnie i usuwamy jabłko z mapy
                    new_room_map[new_y][new_x] = EMPTY
                else:
                    # wąż się nie wydłuża - usuń ogon
                    pdata["positions"].pop()

            # Sprawdź, czy wszyscy gracze są w tym samym pokoju -> ewentualna zmiana self.current_room
            # (opcjonalnie możemy przenieść "centrum gry" gdy wszyscy wejdą do innego pomieszczenia)
            rooms_used = {self.players[p]["room"] for p in self.players if self.players[p]["alive"]}
            if len(rooms_used) == 1 and len(rooms_used) != 0:
                self.current_room = rooms_used.pop()

    def get_adjacent_room(self, current_room, direction):
        """
        Zwraca nazwę sąsiedniego pokoju, jeśli istnieje.
        Prosta implementacja: sprawdź, czy istnieje roomX w self.maps.
        Można rozbudować wg potrzeb (np. room0 -> room1).
        """
        # Przykładowo: room0 -> room1, room1 -> room0 (itp.)
        if current_room == "room0" and direction == "up":
            return None
        if current_room == "room0" and direction == "down":
            return "room1"
        if current_room == "room0" and direction == "left":
            return None
        if current_room == "room0" and direction == "right":
            return None

        if current_room == "room1" and direction == "up":
            return "room0"
        if current_room == "room1" and direction == "down":
            return None
        if current_room == "room1" and direction == "left":
            return None
        if current_room == "room1" and direction == "right":
            return None

        return None

    def teleport_to_room_edge(self, new_room, from_direction, coord):
        """
        Pomocnicza funkcja do "teleportowania" gracza na krawędź nowego pokoju.
        from_direction mówi, z której krawędzi wchodzi gracz (up, down, left, right),
        a coord to np. x lub y z poprzedniego pokoju.
        Zwraca (new_y, new_x).
        """
        height = len(self.maps[new_room])
        width = len(self.maps[new_room][0])

        if from_direction == "up":
            # gracz wchodzi od góry -> spawn na dole
            return (height - 1, coord)
        elif from_direction == "down":
            # gracz wchodzi od dołu -> spawn na górze
            return (0, coord)
        elif from_direction == "left":
            # gracz wchodzi z lewej -> spawn przy prawej krawędzi
            return (coord, width - 1)
        elif from_direction == "right":
            # gracz wchodzi z prawej -> spawn przy lewej krawędzi
            return (coord, 0)

        # domyślnie
        return (height // 2, width // 2)

    def get_game_state(self):
        """
        Zwraca słownik reprezentujący aktualny stan gry, do wysłania klientom.
        """
        with self.lock:
            state = {
                "current_room": self.current_room,
                "players": {},
                "maps": {},  # Możemy wysłać wszystkie mapy lub tylko aktualny pokój
            }

            # Wysyłamy stan każdej mapy jako listę list znaków
            for rname, rmap in self.maps.items():
                state["maps"][rname] = ["".join(row) for row in rmap]

            for pid, pdata in self.players.items():
                state["players"][pid] = {
                    "positions": pdata["positions"],
                    "alive": pdata["alive"],
                    "room": pdata["room"]
                }
            return state


class SnakeServer:
    def __init__(self):
        self.game = SnakeGame()

        # Połączenie z RabbitMQ
        self.connection = pika.BlockingConnection(pika.ConnectionParameters(host='localhost'))
        self.channel = self.connection.channel()

        # Kolejka, z której serwer odbiera wiadomości od wszystkich klientów
        self.server_queue = "server_queue"
        self.channel.queue_declare(queue=self.server_queue)

        # Exchange typu fanout, do rozsyłania aktualnego stanu gry do wszystkich klientów
        self.game_state_exchange = "game_state_exchange"
        self.channel.exchange_declare(exchange=self.game_state_exchange, exchange_type='fanout')

        # Ustawiamy callback do obsługi wiadomości
        self.channel.basic_consume(queue=self.server_queue, on_message_callback=self.on_request, auto_ack=True)

        # Uruchamiamy wątek głównej pętli gry
        self.running = True
        self.update_thread = threading.Thread(target=self.game_loop)
        self.update_thread.start()

    def on_request(self, ch, method, props, body):
        """
        Callback wywoływany po odebraniu wiadomości od klienta.
        """
        message = json.loads(body.decode("utf-8"))
        msg_type = message.get("type")

        if msg_type == "join_game":
            player_id = str(message["player_id"])
            added = self.game.add_player(player_id)
            # Można odesłać odpowiedź, ale w tym przykładzie nie jest to konieczne.
            return

        if msg_type == "player_move":
            player_id = str(message["player_id"])
            direction = message["direction"]
            self.game.update_player_direction(player_id, direction)

    def game_loop(self):
        """
        Główna pętla aktualizująca grę i rozsyłająca stan do klientów.
        """
        while self.running:
            self.game.update()
            # Rozsyłamy stan gry do klientów
            state = self.game.get_game_state()
            self.channel.basic_publish(
                exchange=self.game_state_exchange,
                routing_key='',
                body=json.dumps(state)
            )
            time.sleep(UPDATE_INTERVAL)

    def start_server(self):
        """
        Rozpoczyna nasłuchiwanie na kolejce serwerowej.
        """
        print("Serwer wystartował. Oczekiwanie na klientów...")
        try:
            self.channel.start_consuming()
        except KeyboardInterrupt:
            print("Zamykanie serwera...")
            self.running = False
            self.update_thread.join()
            self.connection.close()


if __name__ == "__main__":
    server = SnakeServer()
    server.start_server()