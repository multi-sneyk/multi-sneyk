# multi-sneyk

#### (Projekt zawiera film pokazowy z wyjaśnieniem)

Klasyka w nowym wydaniu. Snake multi player, gdzie po zdobyciu 5 jabłuszek jesteśmy przeteleportowani do nowej trudniejszej mapy. 

## Funkcje gry
Tryb Wieloosobowy: Gra umożliwia jednoczesne uczestnictwo do 6 graczy.
Mechanika gry: 
-Gracze sterują wężami za pomocą klawiszy w stylu VIM (h, j, k, l)
-Celem jest zebranie co najmniej 5 jabłek na każdej z czterech map, unikając kolizji z innymi graczami, ścianami i własnym ogonem.
Mapy: Po zebraniu wymaganego celu jabłek gra przechodzi na następną mapę.
Rozgrywka w Czasie Rzeczywistym: Węże poruszają się płynnie i jednocześnie, co zwiększa poziom rywalizacji.
Restart Gry: Dostępny globalny restart, umożliwiający powrót do pierwszej mapy i rozpoczęcie rozgrywki od nowa.

## Działanie gry
#### Serwer:

* Serwer zarządza logiką gry, obsługuje mapy i synchronizuje stan gry między graczami.

* Używa RabbitMQ do obsługi komunikacji między klientami a serwerem.

* Obsługuje aktualizację pozycji graczy, dodawanie nowych graczy i rozwiązywanie kolizji.

* Dynamicznie zarządza mapami i generuje jabłka na planszy, utrzymując minimalną liczbę jabłek.

#### Klient:

* Klient zapewnia interfejs w trybie tekstowym (curses), gdzie gracze mogą sterować wężem i obserwować aktualny stan planszy.

* Obsługuje ekran startowy, opis gry oraz ekran rozgrywki.

* Łączy się z RabbitMQ, aby wysyłać polecenia ruchu oraz odbierać aktualny stan gry.

## Wymagania:

* Python 3.x

* RabbitMQ (uruchomiony lokalnie lub zdalnie)

* Moduły: pika, curses (dla curses wymagana konsola wspierająca ten moduł)

Strona serwerowa (RabbitMQ + plik server.py oraz mapy) jest hostowana na serwerze z publicznym adresem IP, dzięki czemu do zagrania wystarczy uruchomić sam client.py.


## Uruchomienie gry

`python3 -m venv ~/sneyk`

`source ~/sneyk/bin/activate`

`pip install pika`

Na systemie Windows dodatkowo instalujemy bibliotekę `windows-curses`.

`pip install windows-curses`

`python3 client.py --player_id 1 --host 20.82.1.111 --user adminowiec --password '.p=o!v0cD5kK2+F3,{c1&DB'`

Do dołączenia innych graczy należy podmienić wartość "player_id".

Gra pomaga wybudować dobre VIMowe nawyki za pomcą pamięci mięśniowe. 
Albo my jesteśmy słabiakami, albo gra faktycznie jest trudna.


