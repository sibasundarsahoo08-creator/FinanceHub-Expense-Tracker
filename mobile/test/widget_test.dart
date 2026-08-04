import 'package:flutter_test/flutter_test.dart';
import 'package:financehub_mobile/main.dart';

void main() {
  testWidgets('FinanceHub starts', (tester) async {
    await tester.pumpWidget(const FinanceHubApp());
    expect(find.text('FinanceHub'), findsWidgets);
  });
}
