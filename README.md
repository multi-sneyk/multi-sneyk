# multi-sneyk

Klasyka w nowym wydaniu. Snake multi player, gdzie po zdobyciu 5 jabłuszek jesteśmy przeteleportowani do nowej trudniejszej mapy. 
Są 4 mapy. 
Sterowanie za pomocą nawigacji znanej z VIM.
Możemy zrestartować grę za pomocą klawisza "R".
Możemy wyłączyć sesję za pomocą klawisza "Q"

Strona serwerowa (RabbitMQ + plik server.py oraz mapy) jest hostowana na serwerze z publicznym adresem IP, dzięki czemu do zagrania wystarczy uruchomić samą client.py.

Do uruchomienia wystarczy użyć poniższych komend:

python3 -m venv ~/sneyk

source ~/sneyk/bin/activate

pip install pika
# na windowsie trzeba jeszcze doinstalować pip install windows-curses

python3 client.py --player_id 1 --host 20.82.1.111 --user adminowiec --password '.p=o!v0cD5kK2+F3,{c1&DB'


Do dołączenia innych graczy należy podmienić wartość "player_id"

Gra pomaga wybudować dobre VIMowe nawyki za pomcą pamięci mięśniowe. 
Albo my jesteśmy słabiakami, albo gra faktycznie jest trudna.
