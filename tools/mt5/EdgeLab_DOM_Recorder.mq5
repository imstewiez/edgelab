//+------------------------------------------------------------------+
//| EdgeLab_DOM_Recorder.mq5                                         |
//| Records MT5 Depth of Market snapshots to CSV for EdgeLab.         |
//| Attach to one chart, set symbols, leave running on VPS/local PC.  |
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"
#property description "Records DOM / MarketBook updates for EdgeLab research."

input string InpSymbols = "XAUUSD,EURUSD,GBPJPY,USDJPY";
input string InpOutputPrefix = "edgelab_dom";
input bool   InpRecordOnlyBookEvents = true;

string Symbols[];
bool   Subscribed[];

string Trim(string value)
{
   StringTrimLeft(value);
   StringTrimRight(value);
   return value;
}

string SideName(const ENUM_BOOK_TYPE type)
{
   if(type == BOOK_TYPE_BUY || type == BOOK_TYPE_BUY_MARKET) return "bid";
   if(type == BOOK_TYPE_SELL || type == BOOK_TYPE_SELL_MARKET) return "ask";
   return "unknown";
}

string SafeSymbolFileName(const string symbol)
{
   string out = symbol;
   StringReplace(out, ".", "_");
   StringReplace(out, "#", "_");
   StringReplace(out, "/", "_");
   return out;
}

string FileNameForSymbol(const string symbol)
{
   string date = TimeToString(TimeCurrent(), TIME_DATE);
   StringReplace(date, ".", "");
   return InpOutputPrefix + "_" + SafeSymbolFileName(symbol) + "_" + date + ".csv";
}

void WriteBookSnapshot(const string symbol)
{
   MqlBookInfo book[];
   if(!MarketBookGet(symbol, book))
   {
      PrintFormat("MarketBookGet(%s) failed. Error=%d", symbol, GetLastError());
      return;
   }

   string file_name = FileNameForSymbol(symbol);
   int handle = FileOpen(file_name, FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI, ',');
   if(handle == INVALID_HANDLE)
   {
      PrintFormat("FileOpen(%s) failed. Error=%d", file_name, GetLastError());
      return;
   }

   if(FileSize(handle) == 0)
   {
      FileWrite(handle, "server_time", "local_microseconds", "symbol", "side", "book_type", "price", "volume", "volume_real", "level_index");
   }

   FileSeek(handle, 0, SEEK_END);

   string ts = TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS);
   ulong micros = GetMicrosecondCount();
   for(int i=0; i<ArraySize(book); i++)
   {
      FileWrite(
         handle,
         ts,
         (string)micros,
         symbol,
         SideName(book[i].type),
         (string)book[i].type,
         DoubleToString(book[i].price, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS)),
         (string)book[i].volume,
         DoubleToString(book[i].volume_real, 8),
         (string)i
      );
   }

   FileClose(handle);
}

int OnInit()
{
   int count = StringSplit(InpSymbols, ',', Symbols);
   ArrayResize(Subscribed, count);

   if(count <= 0)
   {
      Print("No symbols configured.");
      return INIT_FAILED;
   }

   for(int i=0; i<count; i++)
   {
      Symbols[i] = Trim(Symbols[i]);
      Subscribed[i] = false;
      if(Symbols[i] == "") continue;

      SymbolSelect(Symbols[i], true);
      if(MarketBookAdd(Symbols[i]))
      {
         Subscribed[i] = true;
         PrintFormat("Subscribed to DOM for %s", Symbols[i]);
      }
      else
      {
         PrintFormat("MarketBookAdd(%s) failed. DOM may not be available for this broker/symbol. Error=%d", Symbols[i], GetLastError());
      }
   }

   Print("EdgeLab DOM recorder started. CSV files are written to MQL5/Files.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   for(int i=0; i<ArraySize(Symbols); i++)
   {
      if(Subscribed[i])
      {
         MarketBookRelease(Symbols[i]);
         PrintFormat("Released DOM subscription for %s", Symbols[i]);
      }
   }
}

void OnBookEvent(const string &symbol)
{
   for(int i=0; i<ArraySize(Symbols); i++)
   {
      if(Subscribed[i] && symbol == Symbols[i])
      {
         WriteBookSnapshot(symbol);
         return;
      }
   }
}
