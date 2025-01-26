#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import curses

def show_start_screen(stdscr):
    """
    Wyświetla menu główne (retro TUI) z obsługą VIM:
      - k: poprzednia opcja
      - j: następna opcja
      - ENTER: zatwierdź
      - q: wyjdź (opcja 3)

    Zwraca 1, 2 lub 3 w zależności od wybranej opcji.
    """
    curses.curs_set(0)
    stdscr.nodelay(False)
    stdscr.keypad(False)  # wyłączamy strzałki, styl VIM

    options = [
        "Rozpocznij grę multiplayer",
        "Opis gry",
        "Wyjdź z gry"
    ]
    selected_idx = 0

    

    banner = [
            
        "  ___  ___      _ _   _   _____                  _    ",
        "  |  \/  |     | | | (_) /  ___|                | |    ",
        "  | .  . |_   _| | |_ _  \ `--. _ __   ___ _   _| | __ ",
        "  | |\/| | | | | | __| |  `--. \ '_ \ / _ \ | | | |/ / ",
        "  | |  | | |_| | | |_| | /\__/ / | | |  __/ |_| |   <  ",
        "  \_|  |_/\__,_|_|\__|_| \____/|_| |_|\___|\__, |_|\_\ ",
        "                                            __/ |      ",
        "                                           |___/       "
            ]

    while True:
        stdscr.clear()

        # Rysowanie banera (duży napis "MULTI SNEYK")
        start_y = 1
        for i, line in enumerate(banner):
            x = max(0, (curses.COLS // 2) - len(line) // 2)
            stdscr.addstr(start_y + i, x, line, curses.A_BOLD)

        # Autorzy gry na dole
        authors_text = "Autorzy gry: Autor1, Autor2, Autor3"
        stdscr.addstr(curses.LINES - 2, 
                      max(0, (curses.COLS // 2) - len(authors_text) // 2),
                      authors_text, 
                      curses.A_DIM)

        # Rysowanie opcji menu
        menu_start_y = start_y + len(banner) + 2
        for i, opt in enumerate(options):
            x = (curses.COLS // 2) - 15
            y = menu_start_y + i*2
            if i == selected_idx:
                stdscr.attron(curses.A_REVERSE)
                stdscr.addstr(y, x, f"> {opt} <")
                stdscr.attroff(curses.A_REVERSE)
            else:
                stdscr.addstr(y, x, f"  {opt}  ")

        stdscr.refresh()

        key = stdscr.getch()
        if key == ord('k'):
            # Góra
            selected_idx = (selected_idx - 1) % len(options)
        elif key == ord('j'):
            # Dół
            selected_idx = (selected_idx + 1) % len(options)
        elif key in [10, 13]:  # ENTER
            return selected_idx + 1
        elif key == ord('q'):
            # wyjście - traktuj jak 3. opcję (Wyjdź z gry)
            return 3


def show_description(stdscr):
    """
    Ekran opisu gry (klawisze ENTER lub q -> powrót).
    Wyświetla ASCII "lore" w POGRUBIONEJ czcionce, plus przykładową fabułę.
    """
    curses.curs_set(0)
    stdscr.nodelay(False)

    # ASCII "lore" w stylu figlet
    ascii_lore = [
        " _     ___________ _____ ",
        "| |   |  _  | ___ \\  ___|",
        "| |   | | | | |_/ / |__  ",
        "| |   | | | |    /|  __| ",
        "| |___\\ \\_/ / |\\ \\| |___ ",
        "\\_____/\___/\_| \\_\\____/ ",
        "                         ",
        "                         "
    ]

    # Przykładowe linie opisu / fabuły
    lines = [
        "Witaj w krainie Multi Sneyk!",
        "Jako dzielny wąż przemierzasz mroczne komnaty,",
        "zbierając Jabłka Mocy i unikając śmiercionośnych pułapek.",
        "Każde Jabłko przybliża Cię do zwycięstwa,",
        "lecz uważaj na ściany i innych wrogich węży!",
        "",
        "Sterowanie w stylu VIM (h/j/k/l), klawisz 'r' resetuje mapy,",
        "Graj ostrożnie i współzawodnicz z innymi, aby zostać Mistrzem!",
        "",
        "Naciśnij [ENTER] lub [q], by wrócić..."
    ]

    while True:
        stdscr.clear()

        # Rysujemy ASCII "lore" w POGRUBIENIU
        row = 1
        col = 2
        for line in ascii_lore:
            stdscr.addstr(row, col, line, curses.A_BOLD)
            row += 1

        row += 1  # odstęp
        for line in lines:
            stdscr.addstr(row, col, line)
            row += 1

        stdscr.refresh()

        key = stdscr.getch()
        if key in [10, 13, ord('q')]:
            break

