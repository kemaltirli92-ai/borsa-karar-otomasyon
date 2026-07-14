"""BLOK 21 - Guvenlik, Log, Izleme ve Yedekleme (app.ops paketi).

Kurallar ozeti:
- Python 3.12, yalnizca stdlib; gercek ag/subprocess cagrisi YOK.
- Deterministik: saat/disk/istatistik/dump ihtiyaclari ENJEKTE edilir
  (clock, stat_provider, dump_fn); modul icinde dogrudan datetime.now() /
  time.time() cagrisi yapilmaz.
- Puan kilidi: bu paket hisse puani/sinyal URETMEZ; log alan adlarinda
  "puan", "score", "sinyal" gecmez.
- Bildirim kilidi: musteriye bildirim/push/telegram YOK; yonetici
  uyarilari dahili kayit listesidir (dis kanal gonderimi degildir).
- Turkce alan adlari, ASCII tanimlayicilar.
"""
