import 'package:flet/flet.dart';

import 'doc_scanner.dart';

class Extension extends FletExtension {
  @override
  FletService? createService(Control control) {
    switch (control.type) {
      case "DocScanner":
        return DocScannerService(control: control);
      default:
        return null;
    }
  }
}
