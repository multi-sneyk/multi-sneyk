#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Serwer gry Snake wieloosobowej z użyciem RabbitMQ.
W tym wydaniu:
 - Gracze spawnują się w różnych punktach startowych (rogi mapy + inne).
 - Można dołączyć w dowolnym momencie.
 - Po zjedzeniu jabłka wąż się wydłuża.
 - Jabłka respawnują się w losowych, wolnych miejscach mapy.

Wymagane: Python 3, pika, zainstalowany i uruchomiony RabbitMQ.
Użytkownik: adminowiec / hasło: .p=o!v0cD5kK2+F3,{c1&DB!
"""

import os
import threading
import time
import json
import random
import pika

# ----- Ustawienia gry -----
UPDATE_INTERVAL = 0.2  # co ile sekund aktualizujemy stan gry
MAX_PLAYERS = 6        # maksymalna liczba graczy (zwiększone)

# ----- Pomocnicze stałe -----
WALL = '#'
APPLE = 'O'
EMPTY = '.'

# Kierunki ruchu (vim-style)
DIRECTIONS = {
    'h': (0, -1),   # left
    'l': (0, 1),    # right
    'k': (-1, 0),   # up
    'j': (1, 0)     # down
}


class SnakeGame:
    """
    Główna klasa logiki gry. Przechowuje mapy, graczy, obsługuje ruch, kolizje, jabłka i punkty startowe.
    """

    def __init__(self, maps_folder="maps"):
        self.maps = {}
        self.load_maps(maps_folder)

        # Domyślny pokój startowy
        self.current_room = "room0"

        # Gracze: {player_id: {...}}
        self.players = {}
        self.player_count = 0

        # Rozmiar mapy (zakładamy jednorodną wielkość)
        if self.current_room not in self.maps:
            raise ValueError(f"Mapa '{self.current_room}' nie została wczytana.")
        self.height = len(self.maps[self.current_room])
        self.width = len(self.maps[self.current_room][0])

        # Blokada do synchronicznego dostępu
        self.lock = threading.Lock()

        # Przygotuj listę punktów startowych, aby gracze się nie zderzali od razu.
        self.start_positions = self.generate_start_positions()

    def load_maps(self, folder):
        """
        Wczytuje pliki .txt z katalogu `folder` do słownika self.maps.
        Klucz = nazwa pliku (bez .txt). Wartość = 2D lista znaków.
        """
        if not os.path.isdir(folder):
            print(f"[ERROR] Katalog maps '{folder}' nie istnieje.")
            return

        for filename in os.listdir(folder):
            if filename.endswith(".txt"):
                room_name = filename.replace(".txt", "")
                path = os.path.join(folder, filename)
                with open(path, 'r') as f:
                    lines = [list(line.rstrip('\n')) for line in f]
                self.maps[room_name] = lines
                print(f"[INFO] Wczytano mapę '{room_name}' z pliku '{filename}'.")

    def generate_start_positions(self):
        """
        Przygotowuje listę początkowych pozycji dla graczy (różne miejsca na mapie),
        tak aby nie kolidowali przy spawnie.
        Tutaj np. 6 punktów startowych (MAX_PLAYERS).
        Możesz dostosować do własnych potrzeb, np. rogi mapy, środki krawędzi, itp.
        """
        # Punkty np. w rogach i w środku mapy
        # Zwracamy listę (room, y, x) => bo można ewentualnie rozróżnić pokoje, ale tu startujemy w "room0".
        # Gdy graczy jest więcej, bierzemy kolejne z listy.
        points = []
        # rogi
        points.append((self.current_room, 1, 1))  # lewy górny róg
        points.append((self.current_room, 1, self.width - 2))  # prawy górny róg
        points.append((self.current_room, self.height - 2, 1))  # lewy dolny róg
        points.append((self.current_room, self.height - 2, self.width - 2))  # prawy dolny róg

        # jeszcze dwie dodatkowe pozycje bardziej centralne
        points.append((self.current_room, self.height // 2, self.width // 4))
        points.append((self.current_room, self.height // 2, (3 * self.width) // 4))

        return points

    def add_player(self, player_id):
        """
        Dodaje nowego gracza do gry, przypisując mu wolny punkt startowy (z listy).
        Jeśli punkt jest zajęty, to przeszukujemy mapę w poszukiwaniu wolnego pola.
        """
        with self.lock:
            if self.player_count >= MAX_PLAYERS:
                print(f"[WARN] Osiągnięto limit graczy ({MAX_PLAYERS}). Gracz {player_id} nie został dodany.")
                return False

            # Wybierz pozycję startową z listy (wg self.player_count)
            # Jeśli mamy definicję w start_positions
            if self.player_count < len(self.start_positions):
                (start_room, start_y, start_x) = self.start_positions[self.player_count]
            else:
                # jakby było więcej graczy niż przygotowanych punktów,
                # to dajemy z grubsza środek
                start_room = self.current_room
                start_y = self.height // 2
                start_x = self.width // 2

            # Upewnij się, że faktycznie wolne
            if not self.is_empty_cell(start_room, start_y, start_x):
                # Jeśli kolizja, szukamy jakiegokolwiek wolnego
                found = False
                for y in range(1, self.height - 1):
                    for x in range(1, self.width - 1):
                        if self.is_empty_cell(start_room, y, x):
                            start_y = y
                            start_x = x
                            found = True
                            break
                    if found:
                        break
                if not found:
                    print(f"[ERROR] Brak wolnego miejsca dla nowego gracza {player_id}.")
                    return False

            self.players[player_id] = {
                "positions": [(start_y, start_x)],
                "direction": (0, 0),
                "alive": True,
                "room": start_room
            }
            self.player_count += 1
            print(f"[INFO] Dodano gracza {player_id} w pozycji ({start_y}, {start_x}) w pokoju '{start_room}'.")
            return True

    def is_empty_cell(self, room_name, y, x):
        """
        Sprawdza, czy komórka (y, x) jest wolna (można tam wejść).
        Wolne = puste pole lub jabłko.
        """
        room_map = self.maps[room_name]
        cell = room_map[y][x]
        if cell == WALL:
            return False
        # Apple jest dozwolone => da się wejść
        return True

    def update_player_direction(self, player_id, direction):
        """
        Ustawia kierunek (dy, dx) gracza, jeśli gracz żyje.
        """
        with self.lock:
            if player_id in self.players and self.players[player_id]["alive"]:
                if direction in DIRECTIONS:
                    self.players[player_id]["direction"] = DIRECTIONS[direction]
                    print(f"[INFO] Zmieniono kierunek gracza {player_id} na '{direction}'.")

    def update(self):
        """
        Główna metoda aktualizująca stan gry:
         - przesuwa węże
         - sprawdza kolizje
         - obsługuje zjadanie jabłek
         - ewentualnie respawnuje jabłka
        """
        with self.lock:
            dead_players = []

            for pid, pdata in self.players.items():
                if not pdata["alive"]:
                    continue

                (dy, dx) = pdata["direction"]
                if (dy, dx) == (0, 0):
                    # gracz jeszcze nie ruszył
                    continue

                head_y, head_x = pdata["positions"][0]
                new_y = head_y + dy
                new_x = head_x + dx
                current_room = pdata["room"]

                # -- Sprawdź, czy wychodzimy poza mapę => inny pokój lub kolizja --
                if new_y < 0:
                    new_room = self.get_adjacent_room(current_room, "up")
                    if new_room:
                        pdata["room"] = new_room
                        (new_y, new_x) = self.teleport_to_room_edge(new_room, "down", head_x)
                    else:
                        pdata["alive"] = False
                        dead_players.append(pid)
                        print(f"[INFO] Gracz {pid} zderzył się ze ścianą (góra).")
                        continue
                elif new_y >= self.height:
                    new_room = self.get_adjacent_room(current_room, "down")
                    if new_room:
                        pdata["room"] = new_room
                        (new_y, new_x) = self.teleport_to_room_edge(new_room, "up", head_x)
                    else:
                        pdata["alive"] = False
                        dead_players.append(pid)
                        print(f"[INFO] Gracz {pid} zderzył się ze ścianą (dół).")
                        continue
                elif new_x < 0:
                    new_room = self.get_adjacent_room(current_room, "left")
                    if new_room:
                        pdata["room"] = new_room
                        (new_y, new_x) = self.teleport_to_room_edge(new_room, "right", head_y)
                    else:
                        pdata["alive"] = False
                        dead_players.append(pid)
                        print(f"[INFO] Gracz {pid} zderzył się ze ścianą (lewo).")
                        continue
                elif new_x >= self.width:
                    new_room = self.get_adjacent_room(current_room, "right")
                    if new_room:
                        pdata["room"] = new_room
                        (new_y, new_x) = self.teleport_to_room_edge(new_room, "left", head_y)
                    else:
                        pdata["alive"] = False
                        dead_players.append(pid)
                        print(f"[INFO] Gracz {pid} zderzył się ze ścianą (prawo).")
                        continue

                # -- Mapa w nowym pokoju --
                room_map = self.maps[pdata["room"]]

                # -- Kolizja ze ścianą w nowym pokoju --
                if room_map[new_y][new_x] == WALL:
                    pdata["alive"] = False
                    dead_players.append(pid)
                    continue

                # -- Kolizje z ciałami węży --
                for other_pid, other_pdata in self.players.items():
                    if not other_pdata["alive"]:
                        continue
                    if other_pid == pid:
                        # z samym sobą
                        if (new_y, new_x) in other_pdata["positions"]:
                            pdata["alive"] = False
                            dead_players.append(pid)
                            break
                    else:
                        # z innym graczem
                        if other_pdata["room"] == pdata["room"] and (new_y, new_x) in other_pdata["positions"]:
                            pdata["alive"] = False
                            dead_players.append(pid)
                            break

                if pid in dead_players:
                    continue

                # -- Ruch węża (dodaj głowę) --
                pdata["positions"].insert(0, (new_y, new_x))

                # -- Sprawdź, czy zjadł jabłko (wtedy wąż rośnie) --
                if room_map[new_y][new_x] == APPLE:
                    # Zjadł => usuwamy jabłko z mapy
                    room_map[new_y][new_x] = EMPTY
                    print(f"[INFO] Gracz {pid} zjadł jabłko w pokoju {pdata['room']} na ({new_y}, {new_x}).")

                    # W tym miejscu wąż się nie skraca (czyli rośnie o 1)
                    # Jednocześnie respawn nowego jabłka w tym samym pokoju
                    self.spawn_random_apple(pdata["room"])

                else:
                    # Normalny ruch => usuwamy ogon
                    pdata["positions"].pop()

            # -- Jeśli wszyscy żywi gracze w tym samym pokoju => self.current_room to ten pokój
            rooms_used = {self.players[p]["room"] for p in self.players if self.players[p]["alive"]}
            if len(rooms_used) == 1 and len(rooms_used) > 0:
                self.current_room = rooms_used.pop()

    def spawn_random_apple(self, room_name):
        """
        Dodaje jabłko (APPLE) w losowym wolnym miejscu w danym pokoju.
        """
        room_map = self.maps[room_name]
        empty_positions = []
        for y in range(1, self.height - 1):
            for x in range(1, self.width - 1):
                if room_map[y][x] == EMPTY or room_map[y][x] == '.':
                    # Sprawdź, czy nie ma tam ciała żadnego węża
                    # bo is_empty_cell pozwala też na to, że może tam być wąż
                    # my chcemy *rzeczywiście* wolne.
                    if not self.is_snake_on_cell(room_name, y, x):
                        empty_positions.append((y, x))

        if not empty_positions:
            # brak wolnego miejsca
            print("[WARN] Nie można wygenerować nowego jabłka - brak wolnych pól.")
            return

        (rand_y, rand_x) = random.choice(empty_positions)
        room_map[rand_y][rand_x] = APPLE
        print(f"[INFO] Nowe jabłko: room={room_name}, y={rand_y}, x={rand_x}.")

    def is_snake_on_cell(self, room_name, y, x):
        """
        Sprawdza, czy w (y, x) w tym roomie znajduje się jakikolwiek segment węża.
        """
        for pid, pdata in self.players.items():
            if not pdata["alive"]:
                continue
            if pdata["room"] == room_name and (y, x) in pdata["positions"]:
                return True
        return False

    def get_adjacent_room(self, current_room, direction):
        """
        Określa, do którego pokoju trafiamy, wychodząc z current_room w danym kierunku.
        """
        if current_room == "room0":
            if direction == "down":
                return "room1"
            return None
        elif current_room == "room1":
            if direction == "up":
                return "room0"
            return None
        return None

    def teleport_to_room_edge(self, new_room, from_direction, coord):
        """
        Teleportuje gracza na krawędź nowego pokoju.
        from_direction: skąd przyszedł (up, down, left, right),
        coord: x lub y z poprzedniego pokoju
        Zwraca (new_y, new_x).
        """
        height = len(self.maps[new_room])
        width = len(self.maps[new_room][0])

        if from_direction == "up":
            return (height - 1, coord)
        elif from_direction == "down":
            return (0, coord)
        elif from_direction == "left":
            return (coord, width - 1)
        elif from_direction == "right":
            return (coord, 0)

        # domyślnie środek mapy
        return (height // 2, width // 2)

    def get_game_state(self):
        """
        Zwraca dict z aktualnym stanem gry (mapy, gracze, aktualny pokój).
        """
        with self.lock:
            state = {
                "current_room": self.current_room,
                "players": {},
                "maps": {}
            }
            # Dodaj mapy jako listę stringów
            for rname, rmap in self.maps.items():
                state["maps"][rname] = ["".join(row) for row in rmap]

            # Informacje o każdym graczu
            for pid, pdata in self.players.items():
                state["players"][pid] = {
                    "positions": pdata["positions"],
                    "alive": pdata["alive"],
                    "room": pdata["room"]
                }

            return state


class SnakeServer:
    """
    Serwer - utrzymuje stan gry i komunikuje się z klientami przez RabbitMQ.
    """

    def __init__(self):
        self.game = SnakeGame()
        self.running = True

        # --- Połączenie do KONSUMOWANIA (odbieranie) ---
        try:
            self.consume_connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host='localhost',
                    port=5672,
                    virtual_host='/',
                    credentials=pika.PlainCredentials('adminowiec', '.p=o!v0cD5kK2+F3,{c1&DB')
                )
            )
            self.consume_channel = self.consume_connection.channel()
            self.server_queue = "server_queue"
            self.consume_channel.queue_declare(queue=self.server_queue)
            # odbiór wiadomości
            self.consume_channel.basic_consume(
                queue=self.server_queue,
                on_message_callback=self.on_request,
                auto_ack=True
            )
            print("[SERVER] Połączenie do konsumowania utworzone.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] Nie udało się połączyć z RabbitMQ do konsumowania: {e}")
            self.running = False

        # --- Połączenie do PUBLIKOWANIA (wysyłanie stanu gry) ---
        try:
            self.publish_connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host='localhost',
                    port=5672,
                    virtual_host='/',
                    credentials=pika.PlainCredentials('adminowiec', '.p=o!v0cD5kK2+F3,{c1&DB')
                )
            )
            self.publish_channel = self.publish_connection.channel()
            self.game_state_exchange = "game_state_exchange"
            self.publish_channel.exchange_declare(
                exchange=self.game_state_exchange,
                exchange_type='fanout'
            )
            print("[SERVER] Połączenie do publikowania utworzone.")
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[ERROR] Nie udało się połączyć z RabbitMQ do publikowania: {e}")
            self.running = False

        # Uruchamiamy wątek game_loop
        if self.running:
            self.update_thread = threading.Thread(target=self.game_loop, daemon=True)
            self.update_thread.start()
            print("[SERVER] Wątek game_loop uruchomiony.")

    def on_request(self, ch, method, props, body):
        """
        Callback dla wiadomości z kolejki serwera (join_game, player_move).
        """
        try:
            message = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            print("[WARN] Otrzymano niepoprawny JSON.")
            return

        msg_type = message.get("type", "")
        if msg_type == "join_game":
            player_id = str(message.get("player_id"))
            if player_id:
                success = self.game.add_player(player_id)
                if success:
                    print(f"[SERVER] Gracz {player_id} dołączył do gry (dowolny moment).")
                else:
                    print(f"[SERVER] Gracz {player_id} NIE dołączył (limit lub brak miejsca).")
        elif msg_type == "player_move":
            player_id = str(message.get("player_id"))
            direction = message.get("direction")
            if player_id and direction:
                self.game.update_player_direction(player_id, direction)
                print(f"[SERVER] Gracz {player_id} zmienił kierunek na '{direction}'.")
        else:
            print(f"[WARN] Nieznany typ wiadomości: {msg_type}")

    def game_loop(self):
        """
        Wątek pętli gry: aktualizacja stanu i publikacja do klientów.
        """
        while self.running:
            self.game.update()
            state = self.game.get_game_state()
            # Wyślij stan gry
            try:
                self.publish_channel.basic_publish(
                    exchange=self.game_state_exchange,
                    routing_key='',
                    body=json.dumps(state)
                )
            except pika.exceptions.AMQPError as e:
                print(f"[ERROR] Błąd podczas publikowania stanu gry: {e}")
                self.running = False

            time.sleep(UPDATE_INTERVAL)

    def start_server(self):
        if not self.running:
            print("[SERVER] Serwer nie został poprawnie zainicjalizowany. Zamykanie.")
            return

        print("[SERVER] Serwer wystartował. Oczekiwanie na klientów...")
        try:
            self.consume_channel.start_consuming()
        except KeyboardInterrupt:
            print("[SERVER] Przerwano serwer (Ctrl+C).")
        finally:
            self.running = False
            # Zatrzymaj pętlę
            try:
                self.consume_channel.stop_consuming()
            except:
                pass

            if hasattr(self, 'update_thread') and self.update_thread.is_alive():
                self.update_thread.join()

            try:
                self.consume_connection.close()
            except:
                pass

            try:
                self.publish_connection.close()
            except:
                pass

            print("[SERVER] Serwer zamknięty.")


if __name__ == "__main__":
    server = SnakeServer()
    server.start_server()
